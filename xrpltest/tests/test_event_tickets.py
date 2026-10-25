"""Real SDK addresses with mocked ledger evidence; no funded accounts or network."""
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from xrpl.wallet import Wallet

from xrpltest.event_tickets import TicketError, TicketLedger, TicketStore, xrp_text
from xrpltest.server import Handler


class FakeLedger:
    def __init__(self, order=None):
        self.result = None
        self.calls = 0
        if order:
            self.result = {**order['payment_request'], 'hash': 'A' * 64,
                'validated': True, 'ledger_index': 101,
                'meta': {'TransactionResult': 'tesSUCCESS', 'delivered_amount': str(order['price_drops'])}}

    def validated_index(self):
        return 100

    def lookup(self, tx_hash):
        self.calls += 1
        return self.result


class TicketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'tickets.sqlite3'
        self.store = TicketStore(self.path)
        self.receiver = Wallet.create().classic_address
        self.buyer = Wallet.create().classic_address
        self.store.create_event('gallery', 'Gallery opening', 'cultural', self.receiver, '2.000001', 2)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def checkout(self):
        return self.store.checkout('gallery', self.buyer, 100)

    def paid(self):
        order = self.checkout()
        return self.store.verify(FakeLedger(order), order['id'], 'A' * 64)

    def test_checkout_contains_exact_payment_fields_and_no_ticket(self):
        order = self.checkout()
        self.assertEqual(order['payment_request']['Amount'], '2000001')
        self.assertEqual(order['payment_request']['Account'], self.buyer)
        self.assertEqual(order['payment_request']['Destination'], self.receiver)
        self.assertIsNone(order['ticket_code'])
        self.assertEqual(order['status'], 'awaiting_payment')
        self.assertEqual(order['price_xrp'], '2.000001')

    def test_capacity_reservations_across_connections(self):
        self.checkout()
        other = TicketStore(self.path)
        try:
            other.checkout('gallery', self.buyer, 100)
            with self.assertRaises(TicketError):
                self.checkout()
        finally:
            other.db.close()
        self.assertEqual(self.store.event('gallery')['available'], 0)
        self.assertEqual(self.store.event('gallery')['tickets_sold'], 0)

    def test_invalid_event_config(self):
        for kwargs in [{'capacity': True}, {'capacity': 0}, {'price_xrp': '0'},
                       {'receiver': 'invalid'}, {'kind': 'nonprofit'}, {'title': ''}]:
            args = dict(event_id='other', title='Event', kind='corporate', receiver=self.receiver, price_xrp='1', capacity=1)
            args.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.store.create_event(**args)

    def test_rejects_sender_equal_to_recipient_and_invalid_barrier(self):
        with self.assertRaises(TicketError):
            self.store.checkout('gallery', self.receiver, 100)
        for index in [0, -1, True, '100']:
            with self.assertRaises(TicketError):
                self.store.checkout('gallery', self.buyer, index)

    def test_tag_collision_allocates_new_reference(self):
        first = self.checkout()
        with patch('xrpltest.event_tickets.secrets.randbelow', side_effect=[first['destination_tag'] - 1, 3]):
            second = self.checkout()
        self.assertEqual(second['destination_tag'], 4)
        self.assertNotEqual(first['destination_tag'], second['destination_tag'])

    def test_confirmed_payment_issues_exactly_one_ticket(self):
        order = self.checkout()
        ledger = FakeLedger(order)
        paid = self.store.verify(ledger, order['id'], 'a' * 64)
        again = self.store.verify(ledger, order['id'], 'A' * 64)
        self.assertEqual(paid['ticket_code'], again['ticket_code'])
        self.assertGreater(len(paid['ticket_code']), 20)
        self.assertEqual(ledger.calls, 1)
        self.assertEqual(self.store.event('gallery')['tickets_sold'], 1)

    def test_nonfinal_failed_or_missing_payment_never_issues_ticket(self):
        order = self.checkout()
        ledger = FakeLedger(order)
        valid = copy.deepcopy(ledger.result)
        for result in [{'error': 'txnNotFound'}, {**valid, 'validated': False},
                       {**valid, 'meta': {'TransactionResult': 'tecUNFUNDED_PAYMENT'}}]:
            ledger.result = result
            with self.subTest(result=result), self.assertRaises(TicketError):
                self.store.verify(ledger, order['id'], 'A' * 64)
            self.assertIsNone(self.store.order(order['id'])['ticket_code'])

    def test_mismatched_payment_fields_rejected(self):
        order = self.checkout()
        ledger = FakeLedger(order)
        valid = copy.deepcopy(ledger.result)
        for key, value in [('Account', self.receiver), ('Destination', self.buyer),
                           ('DestinationTag', order['destination_tag'] + 1), ('DestinationTag', None),
                           ('TransactionType', 'OfferCreate'), ('hash', 'B' * 64),
                           ('ledger_index', 100), ('ledger_index', None)]:
            ledger.result = {**valid, key: value}
            with self.subTest(field=key), self.assertRaises(TicketError):
                self.store.verify(ledger, order['id'], 'A' * 64)

    def test_partial_token_under_and_overpayments_rejected(self):
        order = self.checkout()
        ledger = FakeLedger(order)
        valid = copy.deepcopy(ledger.result)
        for change in [{'Flags': 0x20000}, {'SendMax': '2000001'}, {'Paths': [[{}]]},
                       {'Amount': '1'}, {'Amount': {'currency': 'USD', 'value': '2'}},
                       {'meta': {'TransactionResult': 'tesSUCCESS', 'delivered_amount': '1'}},
                       {'meta': {'TransactionResult': 'tesSUCCESS', 'delivered_amount': '3000000'}},
                       {'meta': {'TransactionResult': 'tesSUCCESS', 'delivered_amount': 'unavailable'}}]:
            ledger.result = {**valid, **change}
            with self.subTest(change=change), self.assertRaises(TicketError):
                self.store.verify(ledger, order['id'], 'A' * 64)

    def test_missing_metadata_or_invalid_hash_rejected(self):
        order = self.checkout()
        ledger = FakeLedger(order)
        for tx_hash in ['invalid', 'A' * 63, 'G' * 64]:
            with self.assertRaises(TicketError):
                self.store.verify(ledger, order['id'], tx_hash)
        self.assertEqual(ledger.calls, 0)
        ledger.result['meta'] = None
        with self.assertRaises(TicketError):
            self.store.verify(ledger, order['id'], 'A' * 64)

    def test_api_v2_delivermax(self):
        order = self.checkout()
        ledger = FakeLedger(order)
        tx = ledger.result.copy()
        tx['DeliverMax'] = tx.pop('Amount')
        ledger.result = {'validated': True, 'hash': 'A' * 64, 'ledger_index': 101, 'meta': tx['meta'], 'tx_json': tx}
        self.assertEqual(self.store.verify(ledger, order['id'], 'A' * 64)['status'], 'paid')

    def test_same_payment_cannot_fund_two_orders(self):
        self.paid()
        second = self.checkout()
        # Even an inconsistent provider response cannot credit the same hash twice.
        with self.assertRaises(TicketError):
            self.store.verify(FakeLedger(second), second['id'], 'A' * 64)
        self.assertIsNone(self.store.order(second['id'])['ticket_code'])

    def test_confirmed_order_cannot_switch_payment(self):
        paid = self.paid()
        with self.assertRaises(TicketError):
            self.store.verify(FakeLedger(paid), paid['id'], 'B' * 64)

    def test_check_in_once_only(self):
        paid = self.paid()
        self.assertEqual(self.store.check_in(paid['ticket_code'])['checked_in'], 1)
        with self.assertRaises(TicketError):
            self.store.check_in(paid['ticket_code'])
        with self.assertRaises(TicketError):
            self.store.check_in('invalid')

    def test_high_precision_price_text(self):
        self.assertEqual(xrp_text(99999999999999999), '99999999999.999999')
        self.assertEqual(xrp_text(2000000), '2')
        self.assertEqual(xrp_text(1), '0.000001')

    def test_read_only_adapter_validates_latest_ledger(self):
        ledger = TicketLedger()
        with patch.object(ledger.client, 'request') as request:
            request.return_value = SimpleNamespace(result={'validated': True, 'ledger_index': 100})
            self.assertEqual(ledger.validated_index(), 100)
            request.return_value = SimpleNamespace(result={'ledger_index': 100})
            with self.assertRaises(TicketError):
                ledger.validated_index()

    def api(self, method, path, body=None, headers=None):
        handler = object.__new__(Handler)
        handler.server = SimpleNamespace(server_port=8080)
        handler.tickets_db = self.path
        payload = json.dumps(body).encode() if body is not None else b''
        handler.headers = {'Host': '127.0.0.1:8080', 'Content-Type': 'application/json',
                           'Content-Length': str(len(payload)), **(headers or {})}
        handler.rfile = io.BytesIO(payload)
        response = []
        handler.json_response = lambda code, value: response.append((code, value))
        handler.ticket_request(method, path)
        return response[0]

    def test_browser_checkout_api_to_ticket(self):
        code, result = self.api('GET', '/api/tickets/events')
        self.assertEqual(code, 200)
        self.assertEqual(result['events'][0]['title'], 'Gallery opening')
        with patch('xrpltest.event_tickets.TicketLedger', return_value=FakeLedger()):
            code, order = self.api('POST', '/api/tickets/orders', {'event_id': 'gallery', 'buyer': self.buyer})
        self.assertEqual(code, 200)
        with patch('xrpltest.event_tickets.TicketLedger', return_value=FakeLedger(order)):
            code, paid = self.api('POST', '/api/tickets/verify', {'order_id': order['id'], 'tx_hash': 'A' * 64})
        self.assertEqual(code, 200)
        self.assertEqual(paid['status'], 'paid')
        self.assertEqual(self.api('GET', '/api/tickets/orders/' + order['id'])[1]['ticket_code'], paid['ticket_code'])

    def test_browser_rejects_cross_origin_host_and_non_json(self):
        for headers, expected in [({'Origin': 'https://other.example'}, 403),
                                  ({'Host': 'other.example'}, 403),
                                  ({'Content-Type': 'text/plain'}, 415),
                                  ({'Content-Length': '5000'}, 413)]:
            self.assertEqual(self.api('POST', '/api/tickets/orders', {}, headers)[0], expected)

    def test_browser_unknown_order_and_network_failure(self):
        self.assertEqual(self.api('GET', '/api/tickets/orders/missing')[0], 400)
        with patch('xrpltest.event_tickets.TicketLedger', side_effect=RuntimeError('private-provider-detail')):
            code, result = self.api('POST', '/api/tickets/orders', {'event_id': 'gallery', 'buyer': self.buyer})
        self.assertEqual(code, 503)
        self.assertNotIn('private-provider-detail', result['error'])


if __name__ == '__main__':
    unittest.main()
