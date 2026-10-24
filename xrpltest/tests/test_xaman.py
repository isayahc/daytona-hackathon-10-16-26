"""Xaman request ownership, Testnet enforcement, and ledger-confirmed admission."""
import io
import json
import ssl
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from xrpl.wallet import Wallet

from xrpltest.event_tickets import TicketStore
from xrpltest.server import Handler
from xrpltest.xaman import XamanClient, XamanError, XamanFlow, safe_link


class FakeXaman:
    key = 'developer-app-id'

    def __init__(self, account):
        self.account = account
        self.payloads = {}
        self.creates = []
        self.gets = 0

    def create(self, body):
        self.creates.append(body)
        payload_id = str(uuid.uuid4())
        self.payloads[payload_id] = {
            'meta': {'uuid': payload_id, 'resolved': False, 'signed': False, 'expired': False},
            'application': {'uuidv4': self.key}, 'custom_meta': body['custom_meta'],
            'payload': {'tx_type': body['txjson']['TransactionType'], 'request_json': body['txjson'].copy()},
            'response': {'account': self.account, 'environment_nodetype': 'TESTNET', 'txid': 'A' * 64}}
        return {'uuid': payload_id, 'next': {'always': f'https://xumm.app/sign/{payload_id}'},
                'refs': {'qr_png': f'https://xumm.app/sign/{payload_id}_q.png',
                         'websocket_status': f'wss://xumm.app/sign/{payload_id}'}}

    def get(self, payload_id):
        self.gets += 1
        return self.payloads[payload_id]


class Ledger:
    def __init__(self):
        self.result = {'error': 'txnNotFound'}

    def lookup(self, tx_hash):
        return self.result


class XamanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = TicketStore(Path(self.temp.name) / 'tickets.sqlite3')
        self.buyer = Wallet.create().classic_address
        self.receiver = Wallet.create().classic_address
        self.store.create_event('show', 'Evening show', 'cultural', self.receiver, '2', 10)
        self.client = FakeXaman(self.buyer)
        self.flow = XamanFlow(self.store, self.client)
        self.ledger = Ledger()

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def response(self, request):
        return self.client.payloads[self.flow.get(request['id'])['payload_id']]

    def approve(self, request):
        self.response(request)['meta'].update(resolved=True, signed=True)

    def connect(self):
        request = self.flow.create('connect')
        self.approve(request)
        return self.flow.status(request['id'], self.ledger)

    def payment(self):
        connection = self.connect()
        order = self.store.checkout('show', self.buyer, 100)
        request = self.flow.create('payment', connection_id=connection['id'], order_id=order['id'])
        return connection, order, request

    def ledger_success(self, order):
        self.ledger.result = {**order['payment_request'], 'hash': 'A' * 64, 'validated': True,
            'ledger_index': 101, 'meta': {'TransactionResult': 'tesSUCCESS', 'delivered_amount': '2000000'}}

    def test_signin_is_offledger_and_forces_testnet(self):
        request = self.flow.create('connect')
        body = self.client.creates[-1]
        self.assertEqual(body['txjson'], {'TransactionType': 'SignIn'})
        self.assertFalse(body['options']['submit'])
        self.assertEqual(body['options']['force_network'], 'TESTNET')
        self.assertEqual(self.flow.status(request['id'], self.ledger)['status'], 'pending')
        self.approve(request)
        connected = self.flow.status(request['id'], self.ledger)
        self.assertEqual(connected['status'], 'connected')
        self.assertEqual(connected['account'], self.buyer)

    def test_unverified_or_expired_connection_cannot_pay(self):
        pending = self.flow.create('connect')
        with self.assertRaises(XamanError):
            self.flow.account(pending['id'])
        connection = self.connect()
        self.store.db.execute('UPDATE xaman_request SET created_at=0 WHERE id=?', (connection['id'],))
        with self.assertRaises(XamanError):
            self.flow.account(connection['id'])

    def test_payment_is_built_from_order_and_deduplicated(self):
        connection, order, request = self.payment()
        body = self.client.creates[-1]
        self.assertEqual(body['txjson'], order['payment_request'])
        self.assertEqual(body['options']['signers'], [self.buyer])
        self.assertTrue(body['options']['submit'])
        self.assertFalse(body['options']['pathfinding'])
        self.assertEqual(body['options']['force_network'], 'TESTNET')
        again = self.flow.create('payment', connection_id=connection['id'], order_id=order['id'])
        self.assertEqual(again['id'], request['id'])
        self.assertEqual(len(self.client.creates), 2)

    def test_another_wallet_cannot_pay_for_order(self):
        connection = self.connect()
        order = self.store.checkout('show', Wallet.create().classic_address, 100)
        with self.assertRaises(XamanError):
            self.flow.create('payment', connection_id=connection['id'], order_id=order['id'])

    def test_signed_is_not_paid_until_ledger_confirms(self):
        _, order, request = self.payment()
        self.approve(request)
        self.assertEqual(self.flow.status(request['id'], self.ledger)['status'], 'verifying')
        self.assertIsNone(self.store.order(order['id'])['ticket_code'])
        gets = self.client.gets
        self.ledger_success(order)
        result = self.flow.status(request['id'], self.ledger)
        self.assertEqual(result['status'], 'paid')
        self.assertTrue(result['order']['ticket_code'])
        self.assertEqual(self.client.gets, gets)  # Later checks only query the ledger, not Xaman.
        self.assertEqual(self.flow.status(request['id'], self.ledger)['order']['ticket_code'], result['order']['ticket_code'])

    def test_mainnet_and_wrong_signer_rejected(self):
        _, order, request = self.payment()
        self.approve(request)
        self.ledger_success(order)
        response = self.response(request)['response']
        for network in ('MAINNET', 'DEVNET', None):
            response['environment_nodetype'] = network
            with self.subTest(network=network), self.assertRaises(XamanError):
                self.flow.status(request['id'], self.ledger)
        response.update(environment_nodetype='TESTNET', account=self.receiver)
        with self.assertRaises(XamanError):
            self.flow.status(request['id'], self.ledger)
        self.assertIsNone(self.store.order(order['id'])['ticket_code'])

    def test_payload_ownership_and_contents_checked(self):
        _, _, request = self.payment()
        self.approve(request)
        result = self.response(request)
        for container, field, replacement in [(result['meta'], 'uuid', 'other'),
            (result['application'], 'uuidv4', 'other'), (result['custom_meta'], 'identifier', 'other'),
            (result['payload'], 'tx_type', 'AccountDelete'),
            (result['payload']['request_json'], 'Amount', '1')]:
            saved = container[field]
            container[field] = replacement
            with self.subTest(field=field), self.assertRaises(XamanError):
                self.flow.status(request['id'], self.ledger)
            container[field] = saved

    def test_creation_timeout_never_creates_another_payment_request(self):
        connection = self.connect()
        order = self.store.checkout('show', self.buyer, 100)
        with patch.object(self.client, 'create', side_effect=TimeoutError('secret-detail')) as create:
            request = self.flow.create('payment', connection_id=connection['id'], order_id=order['id'])
            again = self.flow.create('payment', connection_id=connection['id'], order_id=order['id'])
        self.assertEqual(create.call_count, 1)
        self.assertEqual(request['status'], 'uncertain')
        self.assertEqual(request['id'], again['id'])
        self.assertNotIn('secret-detail', json.dumps(request))

    def test_signin_failure_is_retryable_and_keeps_safe_error(self):
        with patch.object(self.client, 'create', side_effect=XamanError('Could not reach Xaman.')):
            failed = self.flow.create('connect')
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['message'], 'Could not reach Xaman.')
        self.assertEqual(self.flow.status(failed['id'], self.ledger)['status'], 'failed')
        retried = self.flow.create('connect')
        self.assertEqual(retried['status'], 'pending')
        self.assertNotEqual(retried['id'], failed['id'])

    def test_old_uncertain_signin_is_recovered_without_an_api_call(self):
        request = self.flow.create('connect')
        self.store.db.execute("UPDATE xaman_request SET status='uncertain',payload_id=NULL,links=NULL WHERE id=?", (request['id'],))
        result = self.flow.status(request['id'], self.ledger)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('Connect Xaman', result['message'])
        self.assertEqual(self.client.gets, 0)

    def test_existing_database_gains_error_column_without_losing_requests(self):
        legacy = TicketStore(Path(self.temp.name) / 'legacy.sqlite3')
        try:
            legacy.db.execute('''CREATE TABLE xaman_request (
                id TEXT PRIMARY KEY, kind TEXT, order_id TEXT, payload_id TEXT,
                status TEXT, links TEXT, account TEXT, tx_hash TEXT, created_at INTEGER)''')
            legacy.db.execute("INSERT INTO xaman_request (id,kind,status,created_at) VALUES ('saved','connect','uncertain',1)")
            migrated = XamanFlow(legacy, self.client)
            self.assertEqual(migrated.get('saved')['status'], 'uncertain')
            self.assertIsNone(migrated.get('saved')['error_message'])
            self.assertEqual(migrated.status('saved', self.ledger)['status'], 'failed')
        finally:
            legacy.db.close()

    def test_rejected_request_can_be_replaced(self):
        connection, order, request = self.payment()
        self.response(request)['meta'].update(resolved=True, signed=False)
        self.assertEqual(self.flow.status(request['id'], self.ledger)['status'], 'rejected')
        replacement = self.flow.create('payment', connection_id=connection['id'], order_id=order['id'])
        self.assertNotEqual(request['id'], replacement['id'])

    def test_expired_opened_request_can_still_be_signed(self):
        connection, order, request = self.payment()
        self.response(request)['meta']['expired'] = True
        self.assertEqual(self.flow.status(request['id'], self.ledger)['status'], 'expired')
        self.assertEqual(self.flow.create('payment', connection_id=connection['id'], order_id=order['id'])['id'], request['id'])
        self.approve(request)
        self.ledger_success(order)
        self.assertEqual(self.flow.status(request['id'], self.ledger)['status'], 'paid')

    def test_payment_persists_across_flow_instances(self):
        _, order, request = self.payment()
        reloaded = XamanFlow(self.store, self.client)
        self.approve(request)
        self.ledger_success(order)
        self.assertEqual(reloaded.status(request['id'], self.ledger)['status'], 'paid')

    def test_signed_but_wrong_delivery_is_not_paid(self):
        _, order, request = self.payment()
        self.approve(request)
        self.ledger_success(order)
        self.ledger.result['meta']['delivered_amount'] = '1'
        self.assertEqual(self.flow.status(request['id'], self.ledger)['status'], 'verifying')
        self.assertIsNone(self.store.order(order['id'])['ticket_code'])

    def test_untrusted_links_rejected(self):
        for value in ['javascript:alert(1)', 'https://evil.test/qr', 'https://xumm.app.evil.test',
                      'https://secret@xumm.app/sign', 'http://xumm.app/sign']:
            with self.subTest(value=value), self.assertRaises(XamanError):
                safe_link(value, 'https')

    def api(self, path, body=None):
        handler = object.__new__(Handler)
        handler.server = SimpleNamespace(server_port=8081)
        handler.tickets_db = Path(self.temp.name) / 'tickets.sqlite3'
        raw = json.dumps(body).encode() if body is not None else b''
        handler.headers = {'Host': '127.0.0.1:8081', 'Content-Type': 'application/json', 'Content-Length': str(len(raw))}
        handler.rfile = io.BytesIO(raw)
        responses = []
        handler.json_response = lambda code, value: responses.append((code, value))
        with patch('xrpltest.xaman.XamanClient', return_value=self.client), \
                patch('xrpltest.event_tickets.TicketLedger', return_value=SimpleNamespace(validated_index=lambda: 100)):
            handler.ticket_request('GET' if body is None else 'POST', path)
        return responses[0]

    def test_api_uses_verified_wallet_instead_of_browser_address(self):
        connection = self.connect()
        code, order = self.api('/api/tickets/orders', {'event_id': 'show', 'connection_id': connection['id'], 'buyer': self.receiver})
        self.assertEqual(code, 200)
        self.assertEqual(order['buyer'], self.buyer)
        code, request = self.api('/api/tickets/xaman/pay', {'order_id': order['id'], 'connection_id': connection['id']})
        self.assertEqual(code, 200)
        self.assertEqual(request['kind'], 'payment')

    def test_config_does_not_expose_credentials(self):
        with patch('xrpltest.xaman.credentials', return_value=('private-key', 'private-secret')):
            code, result = self.api('/api/tickets/xaman/config')
        self.assertEqual(result, {'enabled': True, 'network': 'testnet'})

    def test_client_missing_credentials_and_provider_error_are_safe(self):
        with patch('xrpltest.xaman.credentials', return_value=('', '')):
            with self.assertRaises(XamanError):
                XamanClient()
        with patch('xrpltest.xaman.credentials', return_value=('key', 'secret')):
            client = XamanClient()
        error = HTTPError('https://private-url', 401, 'private-reason', {}, io.BytesIO(b'private-body'))
        with patch('xrpltest.xaman.urlopen', side_effect=error), self.assertRaises(XamanError) as raised:
            client.create({'txjson': {'TransactionType': 'SignIn'}})
        self.assertNotIn('private', str(raised.exception))

    def test_client_uses_expected_endpoint_and_headers(self):
        with patch('xrpltest.xaman.credentials', return_value=('key', 'secret')):
            client = XamanClient()
        with patch('xrpltest.xaman.urlopen') as open_url:
            open_url.return_value.__enter__.return_value = io.StringIO('{"uuid":"example"}')
            client.create({'txjson': {'TransactionType': 'SignIn'}})
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, 'https://xumm.app/api/v1/platform/payload')
        self.assertEqual(request.get_header('X-api-secret'), 'secret')
        self.assertEqual(request.get_header('User-agent'), 'CommonGround-XRPLTest/1.0')
        context = open_url.call_args.kwargs['context']
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(json.loads(request.data)['txjson']['TransactionType'], 'SignIn')

    def test_certificate_error_has_actionable_safe_message(self):
        with patch('xrpltest.xaman.credentials', return_value=('key', 'secret')):
            client = XamanClient()
        error = URLError(ssl.SSLCertVerificationError('private TLS diagnostics'))
        with patch('xrpltest.xaman.urlopen', side_effect=error), self.assertRaises(XamanError) as raised:
            client.create({'txjson': {'TransactionType': 'SignIn'}})
        self.assertIn('certificate', str(raised.exception))
        self.assertNotIn('private', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
