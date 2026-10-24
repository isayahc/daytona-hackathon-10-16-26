"""Server-owned Xaman sign requests; wallet keys stay in the attendee's app."""
from __future__ import annotations

import json
import os
import re
import ssl
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import certifi
from dotenv import dotenv_values

from .event_finance import address
from .event_tickets import TicketError, TicketStore

API_URL = 'https://xumm.app/api/v1/platform/payload'


def credentials() -> tuple[str, str]:
    config = dotenv_values(Path(__file__).resolve().with_name('.env'))
    return tuple(str(os.environ.get(name, config.get(name)) or '').strip()
                 for name in ('XAMAN_API_KEY', 'XAMAN_API_SECRET'))


class XamanError(TicketError):
    pass


def safe_link(value: Any, scheme: str) -> str:
    if not isinstance(value, str):
        raise XamanError('Xaman returned an incomplete signing link.')
    parsed = urlsplit(value)
    if (parsed.scheme != scheme or parsed.hostname not in ('xumm.app', 'xaman.app')
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise XamanError('Xaman returned an unexpected signing link.')
    return value


class XamanClient:
    def __init__(self) -> None:
        self.key, self.secret = credentials()
        if not self.key or not self.secret:
            raise XamanError('Xaman is not configured. Add XAMAN_API_KEY and XAMAN_API_SECRET to xrpltest/.env.')

    def request(self, method: str, payload_id: str = '', body: dict | None = None) -> dict:
        url = API_URL + ('/' + str(uuid.UUID(payload_id)) if payload_id else '')
        request = Request(url, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json', 'Accept': 'application/json',
                     'User-Agent': 'CommonGround-XRPLTest/1.0',
                     'X-API-Key': self.key, 'X-API-Secret': self.secret})
        try:
            # Python installations on macOS may have no usable default CA bundle.
            # Keep certificate and hostname verification enabled with certifi's roots.
            context = ssl.create_default_context(cafile=certifi.where())
            with urlopen(request, timeout=20, context=context) as response:
                result = json.load(response)
        except HTTPError as error:
            if error.code == 401:
                message = 'Xaman rejected the app credentials. Check XAMAN_API_KEY and XAMAN_API_SECRET in xrpltest/.env.'
            elif error.code == 403:
                message = 'Xaman refused the request (HTTP 403). Check developer app access and network restrictions.'
            elif error.code == 429:
                message = 'Xaman is rate limiting requests. Wait a little before trying again.'
            else:
                message = f'Xaman returned HTTP {error.code}. Check the developer app settings and try again later.'
            raise XamanError(message) from None
        except URLError as error:
            if isinstance(error.reason, ssl.SSLCertVerificationError):
                message = 'Could not verify Xaman’s HTTPS certificate. Update certifi and check your network’s certificate configuration.'
            else:
                message = 'Could not reach Xaman. Check your internet connection and try again.'
            raise XamanError(message) from None
        except TimeoutError:
            raise XamanError('Xaman did not respond in time. Check the request status before retrying a payment.') from None
        except ValueError:
            raise XamanError('Xaman returned an unreadable response. Check the request status before retrying a payment.') from None
        if not isinstance(result, dict) or result.get('error'):
            raise XamanError('Xaman rejected the request. Check the developer app configuration.')
        return result

    def create(self, body: dict) -> dict:
        return self.request('POST', body=body)

    def get(self, payload_id: str) -> dict:
        return self.request('GET', payload_id)


class XamanFlow:
    """Persist request ownership and never replace an uncertain payment request."""

    def __init__(self, store: TicketStore, client: Any) -> None:
        self.store, self.client = store, client
        store.db.executescript('''
            CREATE TABLE IF NOT EXISTS xaman_request (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, order_id TEXT REFERENCES ticket_order(id),
                payload_id TEXT UNIQUE, status TEXT NOT NULL, links TEXT,
                account TEXT, tx_hash TEXT, created_at INTEGER NOT NULL, error_message TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS xaman_active_payment ON xaman_request(order_id)
                WHERE kind='payment' AND status NOT IN ('rejected', 'cancelled');
        ''')
        # Preserve existing orders and requests while upgrading older demo databases.
        with store.atomic():
            columns = {row['name'] for row in store.db.execute('PRAGMA table_info(xaman_request)')}
            if 'error_message' not in columns:
                store.db.execute('ALTER TABLE xaman_request ADD COLUMN error_message TEXT')

    def get(self, request_id: str) -> dict:
        row = self.store.db.execute('SELECT * FROM xaman_request WHERE id=?', (request_id,)).fetchone()
        if row is None:
            raise XamanError('Wallet request not found. Connect Xaman again.')
        return dict(row)

    def public(self, row: dict) -> dict:
        value = {key: row[key] for key in ('id', 'kind', 'status', 'account', 'order_id', 'tx_hash')}
        if row['links']:
            value.update(json.loads(row['links']))
        if row['error_message']:
            value['message'] = row['error_message']
        return value

    def account(self, connection_id: str) -> str:
        row = self.get(connection_id)
        if (row['kind'] != 'connect' or row['status'] != 'connected'
                or time.time() - row['created_at'] > 3600):
            raise XamanError('Connect your wallet again before continuing.')
        return row['account']

    def create(self, kind: str, *, connection_id: str = '', order_id: str = '') -> dict:
        if kind not in ('connect', 'payment'):
            raise XamanError('Unknown wallet request type.')
        buyer = self.account(connection_id) if kind == 'payment' else None
        with self.store.atomic():
            if kind == 'payment':
                order = self.store.order(order_id)
                if order['buyer'] != buyer:
                    raise XamanError('Connect the wallet used to reserve this ticket.')
                if order['status'] == 'paid':
                    return {'status': 'paid', 'order': order}
                previous = self.store.db.execute('''SELECT * FROM xaman_request WHERE order_id=?
                    AND kind='payment' AND status NOT IN ('rejected', 'cancelled')''', (order_id,)).fetchone()
                if previous:
                    return self.public(dict(previous))
                transaction = order['payment_request']
            else:
                transaction = {'TransactionType': 'SignIn'}
            request_id = str(uuid.uuid4())
            self.store.db.execute('''INSERT INTO xaman_request
                (id,kind,order_id,status,account,created_at) VALUES (?,?,?,'creating',?,?)''',
                (request_id, kind, order_id or None, buyer, int(time.time())))
        options = {'submit': kind == 'payment', 'force_network': 'TESTNET', 'expire': 5,
                   'pathfinding': False}
        if buyer:
            options['signers'] = [buyer]
        body = {'txjson': transaction, 'options': options,
                'custom_meta': {'identifier': request_id, 'instruction':
                    'Connect to Common Ground Testnet checkout' if kind == 'connect'
                    else f"Pay {order['price_xrp']} Testnet XRP for one ticket to {order['title']}"}}
        try:
            result = self.client.create(body)
            payload_id = str(uuid.UUID(result['uuid']))
            # Persist identity even if the provider omits display links.
            self.store.db.execute('UPDATE xaman_request SET payload_id=? WHERE id=?', (payload_id, request_id))
            links = {'open_url': safe_link(result['next']['always'], 'https'),
                     'qr_url': safe_link(result['refs']['qr_png'], 'https'),
                     'websocket_url': safe_link(result['refs']['websocket_status'], 'wss')}
            self.store.db.execute("UPDATE xaman_request SET status='pending',links=? WHERE id=?",
                                  (json.dumps(links), request_id))
        except Exception as error:
            message = str(error) if isinstance(error, XamanError) else 'Could not create the Xaman request. Check the app configuration and connection.'
            # SignIn cannot move funds, so a failed attempt must not lock out retry.
            # Payment creation can have succeeded remotely even if the response was lost.
            status = 'failed' if kind == 'connect' else 'uncertain'
            self.store.db.execute('UPDATE xaman_request SET status=?,error_message=? WHERE id=?',
                                  (status, message, request_id))
        return self.public(self.get(request_id))

    def status(self, request_id: str, ledger: Any) -> dict:
        row = self.get(request_id)
        if row['kind'] == 'connect' and row['status'] in ('uncertain', 'failed'):
            if row['status'] == 'uncertain':
                self.store.db.execute("UPDATE xaman_request SET status='failed',error_message=? WHERE id=?",
                    (row['error_message'] or 'The earlier sign-in request failed. Click Connect Xaman to try again.', request_id))
                row = self.get(request_id)
            return self.public(row)
        if row['kind'] == 'payment':
            order = self.store.order(row['order_id'])
            if order['status'] == 'paid':
                return {**self.public(row), 'status': 'paid', 'order': order}
        if row['status'] in ('connected', 'rejected', 'cancelled'):
            return self.public(row)
        if not row['payload_id']:
            return {**self.public(row), 'message': row['error_message'] or 'Request creation is incomplete or uncertain. Check Xaman before making another payment.'}
        if not row['tx_hash']:
            result = self.client.get(row['payload_id'])
            meta, payload = result.get('meta', {}), result.get('payload', {})
            if (meta.get('uuid') != row['payload_id']
                    or result.get('application', {}).get('uuidv4') != self.client.key
                    or result.get('custom_meta', {}).get('identifier') != row['id']
                    or payload.get('tx_type') != ('SignIn' if row['kind'] == 'connect' else 'Payment')):
                raise XamanError('The wallet response does not match this checkout request.')
            if meta.get('resolved') is True and meta.get('signed') is True:
                response = result.get('response', {})
                signer = response.get('account')
                address(signer)
                if row['kind'] == 'connect':
                    self.store.db.execute("UPDATE xaman_request SET status='connected',account=? WHERE id=?",
                                          (signer, request_id))
                    return self.public(self.get(request_id))
                if signer != row['account']:
                    raise XamanError('A different wallet signed the payment. No ticket was issued.')
                if str(response.get('environment_nodetype', '')).upper() != 'TESTNET':
                    raise XamanError('The payment was not signed on Testnet. No ticket was issued.')
                expected = self.store.order(row['order_id'])['payment_request']
                requested = payload.get('request_json', {})
                if any(requested.get(key) != value for key, value in expected.items()):
                    raise XamanError('Xaman payment details do not match the reserved ticket.')
                tx_hash = response.get('txid')
                if not isinstance(tx_hash, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', tx_hash):
                    raise XamanError('Xaman has not returned a payment hash. Check its status again.')
                self.store.db.execute("UPDATE xaman_request SET status='verifying',tx_hash=? WHERE id=?",
                                      (tx_hash.upper(), request_id))
                row = self.get(request_id)
            else:
                status = ('rejected' if meta.get('resolved') is True and meta.get('signed') is False
                          else 'cancelled' if meta.get('cancelled') is True
                          else 'expired' if meta.get('expired') is True else 'pending')
                self.store.db.execute('UPDATE xaman_request SET status=? WHERE id=?', (status, request_id))
                return self.public(self.get(request_id))
        try:
            order = self.store.verify(ledger, row['order_id'], row['tx_hash'])
        except TicketError as error:
            return {**self.public(row), 'status': 'verifying', 'message': str(error)}
        return {**self.public(row), 'status': 'paid', 'order': order}
