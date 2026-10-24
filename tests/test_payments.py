"""Exercise settlement, policy and retry behavior without spending real funds."""
from __future__ import annotations

import copy
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch

from operator_app.payments import Ledger, Payments, drops, verify_receipt
from operator_app.server import Handler


class FakeLedger:
    """Deterministic ledger double that can lose submission acknowledgements."""

    def __init__(self) -> None:
        """Initialize independent fake wallets and an empty validated ledger."""
        self.addresses = dict(event='event-wallet', attendee='attendee-wallet', vendor='vendor-wallet')
        self.records: dict[str, dict[str, Any]] = {}
        self.submissions = 0
        self.timeout = False

    def prepare(self, invoice: dict[str, Any]) -> tuple[str, str]:
        """Create deterministic transaction evidence for one invoice."""
        tx_hash = f'{len(self.records)+1:064X}'
        self.records[tx_hash] = dict(hash=tx_hash, validated=True, tx_json=dict(
            TransactionType='Payment', Account=self.addresses['attendee' if invoice['kind']=='ticket' else 'event'],
            Destination=invoice['destination'], InvoiceID=invoice['id'], Flags=0),
            meta=dict(TransactionResult='tesSUCCESS', delivered_amount=str(invoice['amount_drops'])))
        return tx_hash, tx_hash

    def submit(self, blob: str) -> dict[str, Any]:
        """Optionally simulate a timeout after the ledger accepted a transaction."""
        self.submissions += 1
        if self.timeout:
            raise TimeoutError('lost acknowledgement')
        return self.records[blob]

    def lookup(self, tx_hash: str) -> dict[str, Any]:
        """Return transaction evidence or a not-found ledger result."""
        return self.records.get(tx_hash, {'error': 'txnNotFound'})


class PaymentTests(unittest.TestCase):
    """Test persistent invoices and deterministic payment authorization."""

    def setUp(self) -> None:
        """Create a fresh local database and fake ledger for each scenario."""
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'payments.sqlite3')
        self.ledger = FakeLedger()
        self.service = Payments(self.path, self.ledger, {'e1', 'e2'}, drops('100'))

    def tearDown(self) -> None:
        """Close the store before removing temporary files."""
        self.service.close()
        self.temp.cleanup()

    def invoice(self, kind: str = 'ticket', amount: str = '20', event: str = 'e1') -> dict[str, Any]:
        """Create a test invoice with an explicit expense authorization."""
        return self.service.create(dict(kind=kind, amount_xrp=amount, event_id=event,
                                        label='Demo', approved=True, min_sales_xrp='20'))

    def test_receipts_unlock_expense_and_survive_restart(self) -> None:
        """Only collected ticket receipts unlock the approved vendor payment."""
        expense = self.invoice('expense', '10')
        with self.assertRaisesRegex(ValueError, 'threshold'):
            self.service.pay(expense['id'])
        ticket = self.invoice()
        self.assertEqual(self.service.pay(ticket['id'])['status'], 'paid')
        self.assertEqual(self.service.pay(expense['id'])['status'], 'paid')
        totals = self.service.snapshot()['totals']['e1']
        self.assertEqual(totals['cash_surplus_xrp'], '10')
        self.service.close()
        self.service = Payments(self.path, self.ledger, {'e1', 'e2'}, drops('100'))
        self.service.pay(expense['id'])
        self.assertEqual(self.ledger.submissions, 2)
        self.assertNotIn('signed_blob', json.dumps(self.service.snapshot()))

    def test_timeout_and_concurrent_retries_do_not_double_pay(self) -> None:
        """Retry after a lost acknowledgement reconciles the persisted hash."""
        ticket = self.invoice()
        self.ledger.timeout = True
        self.assertEqual(self.service.pay(ticket['id'])['status'], 'pending')
        self.service.close()
        self.service = Payments(self.path, self.ledger, {'e1'}, drops('100'))
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(self.service.pay, [ticket['id']]*3))
        self.assertTrue(all(result['status'] == 'paid' for result in results))
        self.assertEqual(self.ledger.submissions, 1)

    def test_budget_and_separate_event_receipts(self) -> None:
        """Prevent overcommitment and spending another event's ticket revenue."""
        self.invoice('expense', '80')
        with self.assertRaisesRegex(ValueError, 'budget'):
            self.invoice('expense', '30')
        ticket = self.invoice(amount='50', event='e2')
        self.service.pay(ticket['id'])
        expense = self.invoice('expense', '10')
        with self.assertRaisesRegex(ValueError, 'threshold'):
            self.service.pay(expense['id'])

    def test_cumulative_payments_cannot_exceed_sales(self) -> None:
        """Multiple approved expenses cannot overspend collected revenue."""
        self.service.pay(self.invoice()['id'])
        self.service.pay(self.invoice('expense', '15')['id'])
        with self.assertRaisesRegex(ValueError, 'insufficient'):
            self.service.pay(self.invoice('expense', '10')['id'])

    def test_unapproved_expenses_and_invalid_inputs(self) -> None:
        """Reject missing approval, unknown events and imprecise money."""
        with self.assertRaises(ValueError):
            self.service.create(dict(kind='expense', event_id='e1', label='test', amount_xrp='10'))
        with self.assertRaises(ValueError):
            self.invoice(event='missing')
        for value in ('NaN', 'Infinity', '-1', '0', '1e2', '0.0000001', 1.2, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                drops(value)
        self.assertEqual(drops('0.000001'), 1)

    def test_receipt_rejects_forged_or_partial_evidence(self) -> None:
        """Require finality, successful delivery, matching invoice and direction."""
        invoice = self.invoice()
        tx_hash, _ = self.ledger.prepare(invoice)
        valid = self.ledger.lookup(tx_hash)
        verify_receipt(invoice, valid, 'event-wallet')
        mutations = [('validated', False), ('meta.TransactionResult', 'tecUNFUNDED_PAYMENT'),
                     ('meta.delivered_amount', '1'), ('meta.delivered_amount', {'currency':'USD','value':'20'}),
                     ('tx_json.Destination', 'someone-else'), ('tx_json.InvoiceID', 'F'*64),
                     ('tx_json.Account', 'event-wallet'), ('tx_json.Flags', 0x20000),
                     ('tx_json.TransactionType', 'AccountDelete')]
        for key, value in mutations:
            with self.subTest(key=key):
                result = copy.deepcopy(valid)
                parts = key.split('.')
                target = result if len(parts) == 1 else result[parts[0]]
                target[parts[-1]] = value
                with self.assertRaises(ValueError):
                    verify_receipt(invoice, result, 'event-wallet')

    def test_external_ticket_and_duplicate_receipt(self) -> None:
        """External tickets can reconcile, but a receipt cannot satisfy two invoices."""
        first, second = self.invoice(), self.invoice()
        tx_hash, _ = self.ledger.prepare(first)
        self.assertEqual(self.service.reconcile(first['id'], tx_hash)['status'], 'paid')
        with self.assertRaises(ValueError):
            self.service.reconcile(second['id'], tx_hash)
        self.assertEqual(self.service.snapshot()['totals']['e1']['received_xrp'], '20')

    def test_unknown_submission_blocks_new_payments(self) -> None:
        """An unresolved transaction reserves spending until reviewed."""
        ticket, other = self.invoice(), self.invoice()
        self.ledger.timeout = True
        pending = self.service.pay(ticket['id'])
        self.ledger.records[pending['tx_hash']]['validated'] = False
        with self.assertRaises(ValueError):
            self.service.pay(ticket['id'])
        with self.assertRaisesRegex(ValueError, 'pending'):
            self.service.pay(other['id'])
        self.assertEqual(self.ledger.submissions, 1)

    def test_validated_failure_can_be_reconciled(self) -> None:
        """A known failed transaction releases the pending-payment barrier."""
        self.ledger.timeout = True
        ticket = self.invoice()
        pending = self.service.pay(ticket['id'])
        self.ledger.records[pending['tx_hash']]['meta']['TransactionResult'] = 'tecUNFUNDED_PAYMENT'
        self.assertEqual(self.service.pay(ticket['id'])['status'], 'failed')
        with self.assertRaisesRegex(ValueError, 'failed'):
            self.service.pay(ticket['id'])

    def test_sdk_signs_real_payment_offline(self) -> None:
        """Exercise the installed SDK serializer and signing API without network."""
        from xrpl.core.binarycodec import decode
        from xrpl.wallet import Wallet
        seeds = {role: Wallet.create().seed for role in ('event', 'attendee', 'vendor')}
        ledger = Ledger(seeds)
        invoice = self.invoice()
        invoice['destination'] = ledger.addresses['event']
        def fill(tx: Any, client: Any) -> Any:
            """Supply ledger fields normally fetched during autofill."""
            return type(tx).from_dict({**tx.to_dict(), 'fee':'12', 'sequence':1, 'last_ledger_sequence':100})
        with patch('xrpl.transaction.autofill', side_effect=fill):
            tx_hash, blob = ledger.prepare(invoice)
        decoded = decode(blob)
        self.assertEqual(len(tx_hash), 64)
        self.assertEqual(decoded['InvoiceID'], invoice['id'])
        self.assertEqual(decoded['Amount'], '20000000')
        self.assertTrue(decoded['TxnSignature'])

    def test_http_flow_and_cross_origin_rejection(self) -> None:
        """Exercise the dashboard endpoints and reject foreign-origin mutations."""
        class TestHandler(Handler):
            """Bind a local fake service without changing the production handler."""
            payments = self.service

            def log_message(self, format: str, *args: Any) -> None:
                """Keep HTTP test logs quiet."""
        server = ThreadingHTTPServer(('127.0.0.1', 0), TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection('127.0.0.1', server.server_port)
            headers = {'Content-Type':'application/json', 'X-Operator-Request':'1'}
            payload = dict(event_id='e1', kind='ticket', label='Ticket', amount_xrp='20')
            connection.request('POST', '/api/xrpl/invoices', json.dumps(payload), headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            invoice = json.loads(response.read())
            connection.request('POST', '/api/xrpl/pay', json.dumps({'invoice_id':invoice['id']}), headers)
            response = connection.getresponse()
            self.assertEqual(json.loads(response.read())['status'], 'paid')
            headers['Origin'] = 'https://attacker.example'
            connection.request('POST', '/api/xrpl/invoices', json.dumps(payload), headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
