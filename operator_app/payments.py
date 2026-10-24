"""Persistent XRPL Testnet invoices and policy-gated event payments.

The model may propose invoices, but only the local operator approves expenses.
Signed transactions are persisted before submission and never silently replaced.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

TESTNET_RPC = 'https://s.altnet.rippletest.net:51234'
EXPLORER = 'https://testnet.xrpl.org/transactions/'


def drops(value: str, *, allow_zero: bool = False) -> int:
    """Parse decimal XRP exactly, rejecting floats, fractions of a drop and NaN."""
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,12}(\.\d{1,6})?', value):
        raise ValueError('Use a decimal XRP string with at most six decimal places.')
    try:
        amount = Decimal(value) * 1_000_000
    except InvalidOperation as exc:
        raise ValueError('Invalid XRP amount.') from exc
    if amount < (0 if allow_zero else 1) or amount > 100_000_000_000_000_000:
        raise ValueError('XRP amount is outside the supported range.')
    return int(amount)


def xrp(value: int) -> str:
    """Format integer drops without introducing floating point rounding."""
    return format(Decimal(value) / 1_000_000, 'f')


class Ledger:
    """Sign locally and communicate only with the public XRPL Testnet."""

    def __init__(self, seeds: dict[str, str]) -> None:
        """Load disposable test wallet seeds without exposing them to the API."""
        from xrpl.clients import JsonRpcClient
        from xrpl.wallet import Wallet
        self.client = JsonRpcClient(TESTNET_RPC)
        self.wallets = {role: Wallet.from_seed(seeds[role]) for role in ('event', 'attendee', 'vendor')}
        self.addresses = {role: wallet.classic_address for role, wallet in self.wallets.items()}
        if len(set(self.addresses.values())) != 3:
            raise ValueError('Use three distinct disposable Testnet wallets.')

    def prepare(self, invoice: dict[str, Any]) -> tuple[str, str]:
        """Autofill and sign a payment, returning its hash and serialized blob."""
        from xrpl.core.binarycodec import encode
        from xrpl.models.transactions import Payment
        from xrpl.transaction import autofill, sign
        wallet = self.wallets['attendee' if invoice['kind'] == 'ticket' else 'event']
        tx = autofill(Payment(account=wallet.classic_address,
                              destination=invoice['destination'], amount=str(invoice['amount_drops']),
                              invoice_id=invoice['id']), self.client)
        if int(tx.fee or '0') > 1000:
            raise ValueError('Testnet fee exceeds the demo cap of 0.001 XRP.')
        signed = sign(tx, wallet)
        return signed.get_hash(), encode(signed.to_xrpl())

    def submit(self, blob: str) -> dict[str, Any]:
        """Submit exactly the persisted signed transaction and await validation."""
        from xrpl.transaction import submit_and_wait
        return submit_and_wait(blob, self.client).result

    def lookup(self, tx_hash: str) -> dict[str, Any]:
        """Fetch transaction evidence directly from the fixed Testnet server."""
        from xrpl.models.requests import Tx
        return self.client.request(Tx(transaction=tx_hash)).result


def verify_receipt(invoice: dict[str, Any], result: dict[str, Any], event_address: str) -> None:
    """Require final successful XRP delivery matching this invoice and direction."""
    tx = result.get('tx_json', result)
    meta = result.get('meta', {})
    if result.get('validated') is not True or not isinstance(meta, dict):
        raise ValueError('Transaction is not yet validated; reconcile again later.')
    if meta.get('TransactionResult') != 'tesSUCCESS':
        raise ValueError('Transaction did not succeed.')
    delivered = meta.get('delivered_amount')
    if (tx.get('TransactionType') != 'Payment' or tx.get('Destination') != invoice['destination']
            or tx.get('InvoiceID') != invoice['id'] or not isinstance(delivered, str)
            or not delivered.isdecimal() or int(delivered) != invoice['amount_drops']
            or int(tx.get('Flags', 0)) & 0x00020000):
        raise ValueError('Receipt must match the invoice, destination and full XRP amount.')
    if invoice['kind'] == 'expense' and tx.get('Account') != event_address:
        raise ValueError('Expense was not paid by the event wallet.')
    if invoice['kind'] == 'ticket' and tx.get('Account') == event_address:
        raise ValueError('Transfers from the event wallet cannot count as ticket sales.')


class Payments:
    """SQLite-backed invoices with serialized spending and restart-safe receipts."""

    def __init__(self, path: str, ledger: Ledger | None, event_ids: set[str], budget: int) -> None:
        """Create a local invoice store bound to this wallet and a per-event budget."""
        self.ledger, self.event_ids, self.budget = ledger, event_ids, budget
        self.lock = RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS invoices (
              id TEXT PRIMARY KEY, event_id TEXT NOT NULL, kind TEXT NOT NULL,
              label TEXT NOT NULL, amount_drops INTEGER NOT NULL, destination TEXT NOT NULL,
              min_sales_drops INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'open',
              tx_hash TEXT UNIQUE, signed_blob TEXT);
        ''')
        if ledger:
            address = ledger.addresses['event']
            previous = self.db.execute("SELECT value FROM settings WHERE key='event_wallet'").fetchone()
            if previous and previous[0] != address:
                raise ValueError('Wallet changed: use a new XRPL_DB_PATH for the new Testnet session.')
            self.db.execute("INSERT OR IGNORE INTO settings VALUES ('event_wallet', ?)", (address,))

    def close(self) -> None:
        """Release the database connection on server shutdown."""
        self.db.close()

    def _invoice(self, invoice_id: str) -> dict[str, Any]:
        """Find an invoice or report a safe validation error."""
        row = self.db.execute('SELECT * FROM invoices WHERE id=?', (invoice_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown invoice.')
        return dict(row)

    def snapshot(self) -> dict[str, Any]:
        """Return public invoice data and event cash accounting without secrets."""
        with self.lock:
            invoices = [dict(row) for row in self.db.execute('SELECT * FROM invoices ORDER BY rowid')]
            for item in invoices:
                item.pop('signed_blob')
                item['amount_xrp'] = xrp(item['amount_drops'])
                item['min_sales_xrp'] = xrp(item['min_sales_drops'])
                item['explorer_url'] = EXPLORER + item['tx_hash'] if item['tx_hash'] else None
            totals = {}
            for event_id in sorted(self.event_ids):
                rows = [i for i in invoices if i['event_id'] == event_id]
                received = sum(i['amount_drops'] for i in rows if i['kind'] == 'ticket' and i['status'] == 'paid')
                paid = sum(i['amount_drops'] for i in rows if i['kind'] == 'expense' and i['status'] == 'paid')
                committed = sum(i['amount_drops'] for i in rows if i['kind'] == 'expense' and i['status'] != 'failed')
                totals[event_id] = dict(received_xrp=xrp(received), paid_xrp=xrp(paid),
                                        committed_xrp=xrp(committed), cash_surplus_xrp=xrp(received-paid),
                                        after_commitments_xrp=xrp(received-committed))
            return dict(network='testnet', enabled=self.ledger is not None,
                        addresses=self.ledger.addresses if self.ledger else {},
                        budget_xrp=xrp(self.budget), invoices=invoices, totals=totals)

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a ticket invoice or explicitly approved expense for a known event."""
        if not self.ledger:
            raise ValueError('Run the Testnet wallet setup and enable XRPL first.')
        event_id, kind = payload.get('event_id'), payload.get('kind')
        label = payload.get('label', '')
        if not isinstance(event_id, str) or event_id not in self.event_ids or kind not in ('ticket', 'expense'):
            raise ValueError('Select a known event and ticket or expense invoice.')
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 120:
            raise ValueError('Provide an invoice label of 1–120 characters.')
        amount = drops(payload.get('amount_xrp'))
        minimum = drops(payload.get('min_sales_xrp', '0'), allow_zero=True)
        if kind == 'expense' and payload.get('approved') is not True:
            raise ValueError('An operator must explicitly approve each expense.')
        destination = self.ledger.addresses['event' if kind == 'ticket' else 'vendor']
        invoice_id = (uuid4().hex + uuid4().hex).upper()
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                if kind == 'expense':
                    committed = self.db.execute("SELECT COALESCE(SUM(amount_drops),0) FROM invoices WHERE event_id=? AND kind='expense' AND status!='failed'", (event_id,)).fetchone()[0]
                    if committed + amount > self.budget:
                        raise ValueError('Expense would exceed this event’s configured budget.')
                self.db.execute('INSERT INTO invoices (id,event_id,kind,label,amount_drops,destination,min_sales_drops) VALUES (?,?,?,?,?,?,?)',
                                (invoice_id, event_id, kind, label.strip(), amount, destination, minimum))
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
            return self._public(invoice_id)

    def _public(self, invoice_id: str) -> dict[str, Any]:
        """Return one invoice without its signed transaction blob."""
        return next(i for i in self.snapshot()['invoices'] if i['id'] == invoice_id)

    def _check_policy(self, invoice: dict[str, Any]) -> None:
        """Allow expenses only against verified event receipts and approved budget."""
        if invoice['kind'] != 'expense':
            return
        totals = self.snapshot()['totals'][invoice['event_id']]
        received = drops(totals['received_xrp'], allow_zero=True)
        paid = drops(totals['paid_xrp'], allow_zero=True)
        if received < invoice['min_sales_drops']:
            raise ValueError('Payment held: verified ticket receipts are below the sales threshold.')
        if paid + invoice['amount_drops'] > received:
            raise ValueError('Payment held: insufficient collected event revenue.')
        if paid + invoice['amount_drops'] > self.budget:
            raise ValueError('Payment held: event spending budget exceeded.')

    def pay(self, invoice_id: str) -> dict[str, Any]:
        """Persist before submission; pending retries reconcile the existing hash only."""
        if not self.ledger:
            raise ValueError('XRPL is disabled.')
        with self.lock:
            invoice = self._invoice(invoice_id)
            if invoice['status'] == 'paid':
                return self._public(invoice_id)
            if invoice['status'] == 'pending':
                return self.reconcile(invoice_id, invoice['tx_hash'])
            if invoice['status'] == 'failed':
                raise ValueError('This transaction failed. Review it before creating another invoice.')
            self.db.execute('BEGIN IMMEDIATE')
            try:
                # Also serialize across server processes sharing this SQLite file.
                invoice = self._invoice(invoice_id)
                if invoice['status'] != 'open':
                    raise ValueError('Invoice state changed. Refresh and reconcile its receipt.')
                if self.db.execute("SELECT 1 FROM invoices WHERE status='pending' LIMIT 1").fetchone():
                    raise ValueError('Reconcile the pending payment before submitting another.')
                self._check_policy(invoice)
                tx_hash, blob = self.ledger.prepare(invoice)
                self.db.execute("UPDATE invoices SET status='pending',tx_hash=?,signed_blob=? WHERE id=?", (tx_hash, blob, invoice_id))
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
            try:
                self.ledger.submit(blob)
            except Exception:
                # Submission may have reached the network. Never sign a replacement.
                return self._public(invoice_id)
            return self.reconcile(invoice_id, tx_hash)

    def reconcile(self, invoice_id: str, tx_hash: str) -> dict[str, Any]:
        """Reconcile immutable Testnet evidence, including externally paid tickets."""
        if not self.ledger or not isinstance(tx_hash, str) or not re.fullmatch(r'[0-9A-Fa-f]{64}', tx_hash):
            raise ValueError('Provide a 64-character Testnet transaction hash.')
        tx_hash = tx_hash.upper()
        with self.lock:
            invoice = self._invoice(invoice_id)
            if invoice['tx_hash'] and invoice['tx_hash'] != tx_hash:
                raise ValueError('Invoice already has a different transaction attached.')
            if invoice['status'] == 'paid':
                return self._public(invoice_id)
            if invoice['kind'] == 'expense' and not invoice['tx_hash']:
                raise ValueError('Submit expenses through the approved payment workflow.')
            result = self.ledger.lookup(tx_hash)
            returned_hash = result.get('hash', result.get('tx_json', {}).get('hash'))
            if not isinstance(returned_hash, str) or returned_hash.upper() != tx_hash:
                raise ValueError('Transaction not found on Testnet; reconcile again later.')
            meta = result.get('meta')
            if invoice['tx_hash'] == tx_hash and result.get('validated') is True and isinstance(meta, dict) and meta.get('TransactionResult', '').startswith(('tec', 'tef')):
                self.db.execute("UPDATE invoices SET status='failed' WHERE id=? AND status='pending'", (invoice_id,))
                return self._public(invoice_id)
            verify_receipt(invoice, result, self.ledger.addresses['event'])
            try:
                self.db.execute("UPDATE invoices SET status='paid', tx_hash=? WHERE id=?", (tx_hash, invoice_id))
            except sqlite3.IntegrityError as exc:
                raise ValueError('This transaction is already assigned to another invoice.') from exc
            return self._public(invoice_id)


def configured_payments(event_ids: set[str]) -> Payments:
    """Load local Testnet-only configuration; never contact a faucet at startup."""
    ledger = None
    if os.getenv('XRPL_ENABLED', 'false').lower() == 'true':
        path = Path(os.getenv('XRPL_WALLET_FILE', '.xrpl-wallets.json'))
        data = json.loads(path.read_text())
        if data.get('network') != 'testnet':
            raise ValueError('Only disposable Testnet wallets are supported.')
        ledger = Ledger(data['seeds'])
    return Payments(os.getenv('XRPL_DB_PATH', '.xrpl-payments.sqlite3'), ledger, event_ids,
                    drops(os.getenv('XRPL_EVENT_BUDGET_XRP', '100')))


def main() -> None:
    """Provision three faucet-funded test wallets into a private local file."""
    from dotenv import load_dotenv
    from xrpl.clients import JsonRpcClient
    from xrpl.wallet import generate_faucet_wallet
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', action='store_true', required=True)
    parser.add_argument('--wallet-file', default=os.getenv('XRPL_WALLET_FILE', '.xrpl-wallets.json'))
    args = parser.parse_args()
    # Exclusive creation prevents accidentally overwriting an existing demo wallet.
    fd = os.open(args.wallet_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    data: dict[str, Any] = {'network': 'testnet', 'seeds': {}}
    with os.fdopen(fd, 'w') as output:
        for role in ('event', 'attendee', 'vendor'):
            wallet = generate_faucet_wallet(JsonRpcClient(TESTNET_RPC), debug=False)
            data['seeds'][role] = wallet.seed
            output.seek(0)
            json.dump(data, output)
            output.truncate()
            output.flush()
            print(f'{role}: {wallet.classic_address}', flush=True)
    print('Testnet wallets saved. Set XRPL_ENABLED=true and start operator_app.server.')


if __name__ == '__main__':
    main()
