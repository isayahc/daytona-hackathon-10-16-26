"""Payment-policy and ledger-finality checks; no network or funded wallets."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from xrpl.models.transactions import Payment
from xrpl.transaction import sign
from xrpl.wallet import Wallet

from xrpltest.event_finance import FinanceStore, MAX_FEE_DROPS, TestnetLedger, drops, pay, reconcile


class FakeLedger:
    def __init__(self, wallet):
        self.wallet = wallet
        self.signed = None
        self.submissions = 0
        self.timeout = False
        self.response = None

    def prepare(self, payment, sender):
        self.signed = sign(Payment(account=sender, destination=payment['destination'],
            destination_tag=payment['destination_tag'], amount=str(payment['amount']),
            sequence=1, fee='12', last_ledger_sequence=100), self.wallet)
        return self.signed

    def submit(self, signed):
        self.submissions += 1
        if self.timeout:
            raise TimeoutError('uncertain')

    def lookup(self, tx_hash):
        if self.response is not None:
            return self.response
        return {**self.signed.to_xrpl(), 'hash': tx_hash, 'validated': True,
                'ledger_index': 90, 'meta': {'TransactionResult': 'tesSUCCESS',
                                          'delivered_amount': self.signed.amount}}


class FinanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'finance.sqlite3'
        self.store = FinanceStore(self.path)
        self.wallet = Wallet.create()
        self.destination = Wallet.create().classic_address
        self.vendors = {'venue': {'address': self.destination, 'destination_tag': 42}}
        self.store.create_event('launch', 'corporate', self.wallet.classic_address, '10', '6', self.vendors)
        self.ledger = FakeLedger(self.wallet)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()

    def tearDown(self):
        self.output.__exit__(None, None, None)
        self.store.db.close()
        self.temp.cleanup()

    def draft(self, amount='3', invoice='venue-001'):
        return self.store.propose('launch', 'venue', invoice, amount)

    def send(self, payment):
        return pay(self.store, self.ledger, payment['id'], confirm=lambda _: f"PAY {payment['id']}")

    def test_exact_amounts(self):
        self.assertEqual(drops('0.000001'), 1)
        self.assertEqual(drops('1.234567'), 1234567)
        for value in ['0', '-1', 'NaN', 'Infinity', '1e3', '1.0000001', ' 1', '100000000001', 1.5]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                drops(value)

    def test_vendor_and_payment_limit(self):
        with self.assertRaises(ValueError):
            self.store.propose('launch', 'unknown', 'inv', '1')
        with self.assertRaises(ValueError):
            self.draft('7')
        self.assertEqual(self.draft()['destination_tag'], 42)

    def test_invalid_vendor_address_and_tag(self):
        for vendor in [{'address': 'not-an-address'}, {'address': self.destination, 'destination_tag': True},
                       {'address': self.destination, 'destination_tag': 2**32}]:
            with self.subTest(vendor=vendor), self.assertRaises(ValueError):
                self.store.create_event('other', 'cultural', self.wallet.classic_address, '10', '5', {'v': vendor})

    def test_duplicate_invoice(self):
        self.draft()
        with self.assertRaises(ValueError):
            self.draft(invoice=' venue-001 ')

    def test_cancel_never_signs_or_reserves(self):
        payment = self.draft()
        result = pay(self.store, self.ledger, payment['id'], confirm=lambda _: 'NO')
        self.assertEqual(result['status'], 'draft')
        self.assertIsNone(self.ledger.signed)
        self.assertEqual(self.store.summary('launch')['available_drops'], 10000000)

    def test_success_receipt_and_no_duplicate_send(self):
        payment = self.draft()
        result = self.send(payment)
        self.assertEqual(result['status'], 'paid')
        self.assertEqual(result['reserved'], 3000012)
        self.assertEqual(result['ledger_index'], 90)
        with self.assertRaises(ValueError):
            self.send(payment)
        self.assertEqual(self.ledger.submissions, 1)

    def test_budget_includes_actual_fees(self):
        self.send(self.draft('6'))
        with self.assertRaises(ValueError):
            self.send(self.draft('4', 'venue-002'))
        self.assertEqual(self.ledger.submissions, 1)

    def test_timeout_holds_budget_and_reconcile_does_not_resend(self):
        payment = self.draft()
        self.ledger.timeout = True
        result = self.send(payment)
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(result['reserved'], 3000000 + MAX_FEE_DROPS)
        self.assertIsNotNone(result['tx_hash'])
        self.assertEqual(reconcile(self.store, self.ledger, payment['id'])['status'], 'paid')
        self.assertEqual(self.ledger.submissions, 1)

    def test_unvalidated_success_is_not_paid(self):
        self.ledger.response = {'validated': False, 'meta': {'TransactionResult': 'tesSUCCESS'}}
        result = self.send(self.draft())
        self.assertEqual(result['status'], 'submitted')
        self.assertEqual(result['reserved'], 3000000 + MAX_FEE_DROPS)

    def test_missing_transaction_keeps_reservation(self):
        self.ledger.response = {'error': 'txnNotFound'}
        self.assertEqual(self.send(self.draft())['status'], 'submitted')

    def test_mismatched_ledger_evidence_cannot_mark_paid(self):
        payment = self.draft()
        self.ledger.timeout = True
        self.send(payment)
        for field, bad in [('Destination', self.wallet.classic_address), ('hash', '0' * 64),
                           ('Amount', '1'), ('DestinationTag', 43)]:
            self.ledger.response = None
            self.ledger.response = {**self.ledger.lookup(self.ledger.signed.get_hash()), field: bad}
            with self.subTest(field=field), self.assertRaises(ValueError):
                reconcile(self.store, self.ledger, payment['id'])
        self.assertEqual(self.store.get(payment['id'])['status'], 'needs_review')

    def test_delivered_amount_must_match(self):
        payment = self.draft()
        self.ledger.timeout = True
        self.send(payment)
        self.ledger.response = self.ledger.lookup(self.ledger.signed.get_hash())
        self.ledger.response['meta']['delivered_amount'] = '1'
        with self.assertRaises(ValueError):
            reconcile(self.store, self.ledger, payment['id'])

    def test_validated_failure_charges_only_fee(self):
        payment = self.draft()
        self.ledger.timeout = True
        self.send(payment)
        self.ledger.response = self.ledger.lookup(self.ledger.signed.get_hash())
        self.ledger.response['meta'] = {'TransactionResult': 'tecUNFUNDED_PAYMENT'}
        result = reconcile(self.store, self.ledger, payment['id'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['reserved'], 12)

    def test_api_v2_transaction_shape(self):
        payment = self.draft()
        self.ledger.timeout = True
        self.send(payment)
        result = self.ledger.lookup(self.ledger.signed.get_hash())
        self.ledger.response = {key: result[key] for key in ('hash', 'validated', 'ledger_index', 'meta')}
        self.ledger.response['tx_json'] = self.ledger.signed.to_xrpl()
        self.ledger.response['tx_json']['DeliverMax'] = self.ledger.response['tx_json'].pop('Amount')
        self.assertEqual(reconcile(self.store, self.ledger, payment['id'])['status'], 'paid')

    def test_same_wallet_pending_across_events_and_connections(self):
        self.store.claim(self.draft()['id'])
        other = FinanceStore(self.path)
        try:
            other.create_event('festival', 'cultural', self.wallet.classic_address, '10', '6', self.vendors)
            payment = other.propose('festival', 'venue', 'festival-001', '1')
            with self.assertRaises(ValueError):
                other.claim(payment['id'])
        finally:
            other.db.close()

    def test_hash_persisted_before_submit(self):
        payment = self.draft()
        with patch.object(self.ledger, 'submit') as submit:
            def check(signed):
                saved = self.store.get(payment['id'])
                self.assertEqual(saved['status'], 'submitted')
                self.assertEqual(saved['tx_hash'], signed.get_hash())
                self.assertEqual(json.loads(saved['signed_json']), signed.to_xrpl())
            submit.side_effect = check
            self.assertEqual(self.send(payment)['status'], 'paid')

    def test_prepare_failure_releases_reservation_and_hides_error(self):
        payment = self.draft()
        with patch.object(self.ledger, 'prepare', side_effect=ValueError('secret-seed')):
            with self.assertRaises(RuntimeError) as raised:
                self.send(payment)
        self.assertNotIn('secret-seed', str(raised.exception))
        self.assertEqual(self.store.get(payment['id'])['status'], 'draft')
        self.assertEqual(self.store.summary('launch')['available_drops'], 10000000)
        self.assertEqual(self.ledger.submissions, 0)

    def test_real_adapter_signs_locally_and_rejects_high_fee(self):
        payment = self.draft()
        ledger = TestnetLedger()
        def fill(transaction, client):
            return Payment(account=transaction.account, destination=transaction.destination,
                destination_tag=transaction.destination_tag, amount=transaction.amount,
                sequence=1, fee='12', last_ledger_sequence=100)
        with patch.dict('os.environ', {'XRPL_TESTNET_SEED': self.wallet.seed}), \
                patch('xrpl.transaction.autofill', side_effect=fill):
            signed = ledger.prepare(payment, self.wallet.classic_address)
            self.assertEqual(signed.amount, '3000000')
            self.assertEqual(signed.destination_tag, 42)
            self.assertIsNotNone(signed.txn_signature)
        expensive = Payment(account=self.wallet.classic_address, destination=self.destination,
            amount='3000000', sequence=1, fee=str(MAX_FEE_DROPS + 1), last_ledger_sequence=100)
        with patch.dict('os.environ', {'XRPL_TESTNET_SEED': self.wallet.seed}), \
                patch('xrpl.transaction.autofill', return_value=expensive), self.assertRaises(ValueError):
            ledger.prepare(payment, self.wallet.classic_address)


if __name__ == '__main__':
    unittest.main()
