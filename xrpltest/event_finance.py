"""Event-linked, organizer-approved XRP vendor payments on XRPL Testnet."""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

TESTNET_URL = 'https://s.altnet.rippletest.net:51234/'
MAX_FEE_DROPS = 1000
MAX_DROPS = 100_000_000_000_000_000


def drops(value: str) -> int:
    """Parse explicit XRP units exactly, never through floating point."""
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,12}(?:\.[0-9]{1,6})?', value):
        raise ValueError('Use a positive XRP amount with at most six decimal places')
    whole, _, fraction = value.partition('.')
    amount = int(whole) * 1_000_000 + int(fraction.ljust(6, '0'))
    if not 0 < amount <= MAX_DROPS:
        raise ValueError('XRP amount is outside the supported range')
    return amount


def address(value: str) -> None:
    from xrpl.core.addresscodec import is_valid_classic_address
    if not isinstance(value, str) or not is_valid_classic_address(value):
        raise ValueError('Use a valid XRPL classic address; specify destination tags separately')


class FinanceStore:
    """Local single-operator storage; policy and payment amounts are immutable."""

    def __init__(self, path: str | Path) -> None:
        self.db = sqlite3.connect(path, timeout=15, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys = ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS event_policy (
                event_id TEXT PRIMARY KEY, kind TEXT NOT NULL, sender TEXT NOT NULL,
                budget INTEGER NOT NULL, payment_limit INTEGER NOT NULL, vendors TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS payment (
                id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES event_policy(event_id),
                vendor TEXT NOT NULL, invoice TEXT NOT NULL, amount INTEGER NOT NULL,
                destination TEXT NOT NULL, destination_tag INTEGER,
                status TEXT NOT NULL DEFAULT 'draft', reserved INTEGER NOT NULL DEFAULT 0,
                tx_hash TEXT, signed_json TEXT, ledger_index INTEGER, result_code TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(event_id, invoice)
            );
        ''')

    @contextmanager
    def atomic(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def policy(self, event_id: str) -> dict[str, Any]:
        row = self.db.execute('SELECT * FROM event_policy WHERE event_id=?', (event_id,)).fetchone()
        if row is None:
            raise ValueError('Event policy not found')
        return dict(row)

    def create_event(self, event_id: str, kind: str, sender: str, budget: str,
                     payment_limit: str, vendors: dict[str, Any]) -> None:
        if not event_id.strip() or kind not in ('cultural', 'corporate'):
            raise ValueError('Provide an event ID and cultural or corporate event type')
        address(sender)
        budget_amount, limit = drops(budget), drops(payment_limit)
        if limit + MAX_FEE_DROPS > budget_amount:
            raise ValueError('Budget must cover the payment limit plus the maximum network fee')
        if not isinstance(vendors, dict) or not vendors:
            raise ValueError('Provide at least one approved vendor')
        for name, vendor in vendors.items():
            if not isinstance(name, str) or not name.strip() or not isinstance(vendor, dict):
                raise ValueError('Each vendor needs a name and address object')
            if set(vendor) - {'address', 'destination_tag'}:
                raise ValueError('Vendor fields are address and optional destination_tag')
            address(vendor.get('address'))
            if vendor['address'] == sender:
                raise ValueError('Vendor and event sender must be different accounts')
            tag = vendor.get('destination_tag')
            if tag is not None and (type(tag) is not int or not 0 <= tag <= 2**32 - 1):
                raise ValueError('Destination tag must be an unsigned 32-bit integer')
        self.db.execute('INSERT INTO event_policy VALUES (?, ?, ?, ?, ?, ?)',
                        (event_id, kind, sender, budget_amount, limit, json.dumps(vendors)))

    def propose(self, event_id: str, vendor: str, invoice: str, amount_xrp: str) -> dict[str, Any]:
        policy = self.policy(event_id)
        approved = json.loads(policy['vendors']).get(vendor)
        amount = drops(amount_xrp)
        invoice = invoice.strip()
        if not approved:
            raise ValueError('Vendor is not on the organizer-approved list')
        if not invoice.strip() or len(invoice) > 200:
            raise ValueError('Provide a unique invoice reference of 1–200 characters')
        if amount > policy['payment_limit']:
            raise ValueError('Payment exceeds the event payment limit')
        payment_id = str(uuid.uuid4())
        try:
            self.db.execute('''INSERT INTO payment
                (id, event_id, vendor, invoice, amount, destination, destination_tag)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (payment_id, event_id, vendor, invoice, amount, approved['address'], approved.get('destination_tag')))
        except sqlite3.IntegrityError as error:
            raise ValueError('This event already has a payment for that invoice') from error
        return self.get(payment_id)

    def get(self, payment_id: str) -> dict[str, Any]:
        row = self.db.execute('SELECT * FROM payment WHERE id=?', (payment_id,)).fetchone()
        if row is None:
            raise ValueError('Payment not found')
        return dict(row)

    def claim(self, payment_id: str) -> dict[str, Any]:
        """Reserve budget and prevent concurrent or repeated sends in this database."""
        with self.atomic():
            payment = self.get(payment_id)
            policy = self.policy(payment['event_id'])
            if payment['status'] != 'draft':
                raise ValueError('Payment was already attempted; reconcile its existing transaction')
            pending = self.db.execute('''SELECT 1 FROM payment p JOIN event_policy e USING(event_id)
                WHERE e.sender=? AND p.status IN ('attempting', 'submitted', 'needs_review')''',
                (policy['sender'],)).fetchone()
            if pending:
                raise ValueError('Reconcile the pending payment from this wallet before sending another')
            spent = self.db.execute('SELECT COALESCE(SUM(reserved),0) FROM payment WHERE event_id=?',
                                    (payment['event_id'],)).fetchone()[0]
            reservation = payment['amount'] + MAX_FEE_DROPS
            if spent + reservation > policy['budget']:
                raise ValueError('Payment plus fee would exceed the remaining event budget')
            self.db.execute("UPDATE payment SET status='attempting', reserved=? WHERE id=?",
                            (reservation, payment_id))
        return self.get(payment_id)

    def summary(self, event_id: str) -> dict[str, Any]:
        policy = self.policy(event_id)
        rows = [dict(row) for row in self.db.execute(
            'SELECT id, vendor, invoice, amount, status, reserved, tx_hash FROM payment WHERE event_id=?', (event_id,))]
        return {'event_id': event_id, 'kind': policy['kind'], 'network': 'testnet',
                'budget_drops': policy['budget'],
                'available_drops': policy['budget'] - sum(row['reserved'] for row in rows), 'payments': rows}


class TestnetLedger:
    """Fixed Testnet endpoint. Keys are used locally, never placed in agent prompts."""

    def __init__(self) -> None:
        from xrpl.clients import JsonRpcClient
        self.client = JsonRpcClient(TESTNET_URL)

    def prepare(self, payment: dict[str, Any], sender: str) -> Any:
        from xrpl.models.transactions import Payment
        from xrpl.transaction import autofill, sign
        from xrpl.wallet import Wallet
        seed = os.environ.get('XRPL_TESTNET_SEED')
        if not seed:
            raise ValueError('Set XRPL_TESTNET_SEED locally using a dedicated Testnet wallet')
        wallet = Wallet.from_seed(seed)
        if wallet.classic_address != sender:
            raise ValueError('Signing wallet does not match the event sender')
        transaction = autofill(Payment(account=sender, destination=payment['destination'],
            destination_tag=payment['destination_tag'], amount=str(payment['amount'])), self.client)
        if not transaction.fee or not 0 < int(transaction.fee) <= MAX_FEE_DROPS:
            raise ValueError('Network fee exceeds the configured cap')
        if transaction.last_ledger_sequence is None:
            raise ValueError('Transaction must expire if it is not validated')
        return sign(transaction, wallet)

    def submit(self, signed: Any) -> None:
        from xrpl.transaction import submit_and_wait
        submit_and_wait(signed, self.client)

    def lookup(self, tx_hash: str) -> dict[str, Any]:
        from xrpl.models.requests import Tx
        return self.client.request(Tx(transaction=tx_hash)).result


def reconcile(store: FinanceStore, ledger: Any, payment_id: str) -> dict[str, Any]:
    """Only a validated, matching transaction can produce a paid receipt."""
    payment = store.get(payment_id)
    if payment['status'] in ('paid', 'failed'):
        return payment
    if not payment['tx_hash']:
        raise ValueError('No saved transaction hash; payment has not reached submission')
    result = ledger.lookup(payment['tx_hash'])
    tx = result.get('tx_json', result)
    metadata = result.get('meta')
    if result.get('validated') is not True or not isinstance(metadata, dict):
        return payment
    signed = json.loads(payment['signed_json'])
    if result.get('hash', tx.get('hash')) != payment['tx_hash']:
        raise ValueError('Ledger response does not match the saved transaction hash')
    for key in ('TransactionType', 'Account', 'Destination', 'DestinationTag', 'Fee', 'Sequence'):
        if tx.get(key) != signed.get(key):
            raise ValueError('Ledger transaction differs from the approved payment')
    if tx.get('Amount', tx.get('DeliverMax')) != str(payment['amount']):
        raise ValueError('Ledger amount differs from the approved payment')
    code = metadata.get('TransactionResult')
    index = result.get('ledger_index')
    if not isinstance(code, str) or type(index) is not int or index <= 0:
        raise ValueError('Ledger response is missing final result evidence')
    if code == 'tesSUCCESS':
        if metadata.get('delivered_amount') != str(payment['amount']):
            raise ValueError('Ledger does not confirm delivery of the exact approved amount')
        status, spent = 'paid', payment['amount'] + int(signed['Fee'])
    else:
        status, spent = 'failed', int(signed['Fee'])
    store.db.execute('''UPDATE payment SET status=?, reserved=?, ledger_index=?, result_code=?
        WHERE id=? AND status IN ('submitted', 'needs_review')''', (status, spent, index, code, payment_id))
    return store.get(payment_id)


def pay(store: FinanceStore, ledger: Any, payment_id: str, *, confirm=input) -> dict[str, Any]:
    payment = store.get(payment_id)
    policy = store.policy(payment['event_id'])
    print(json.dumps({'network': 'testnet', 'sender': policy['sender'],
        'amount_drops': payment['amount'], 'max_fee_drops': MAX_FEE_DROPS,
        **{key: payment[key] for key in
        ('id', 'event_id', 'vendor', 'invoice', 'destination', 'destination_tag', 'status')}}, indent=2))
    if confirm(f'Type PAY {payment_id} to send this Testnet payment: ') != f'PAY {payment_id}':
        return payment
    payment = store.claim(payment_id)
    try:
        signed = ledger.prepare(payment, policy['sender'])
        # Persist signed transaction and hash BEFORE any network submission. Never re-sign on a timeout.
        store.db.execute("UPDATE payment SET status='submitted', tx_hash=?, signed_json=? WHERE id=?",
                         (signed.get_hash(), json.dumps(signed.to_xrpl()), payment_id))
    except Exception:
        store.db.execute("UPDATE payment SET status='draft', reserved=0 WHERE id=? AND status='attempting'",
                         (payment_id,))
        raise RuntimeError('Preparation failed before submission; check wallet, balance, and network settings') from None
    try:
        ledger.submit(signed)
        return reconcile(store, ledger, payment_id)
    except Exception:
        store.db.execute("UPDATE payment SET status='needs_review' WHERE id=? AND status='submitted'", (payment_id,))
        return store.get(payment_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=Path(__file__).resolve().with_name('event-finance.sqlite3'))
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init', help='Organizer: create an immutable event budget and approved vendor list')
    init.add_argument('--event', required=True)
    init.add_argument('--kind', choices=['cultural', 'corporate'], required=True)
    init.add_argument('--sender', required=True)
    init.add_argument('--budget-xrp', required=True)
    init.add_argument('--payment-limit-xrp', required=True)
    init.add_argument('--vendors-file', type=Path, required=True)
    draft = sub.add_parser('propose', help='Prepare a payment without accessing a signing key')
    draft.add_argument('--event', required=True)
    draft.add_argument('--vendor', required=True)
    draft.add_argument('--invoice', required=True)
    draft.add_argument('--amount-xrp', required=True)
    for name in ('show', 'pay', 'reconcile'):
        sub.add_parser(name).add_argument('payment_id')
    sub.add_parser('budget').add_argument('--event', required=True)
    args = parser.parse_args()
    store = FinanceStore(args.db)
    try:
        if args.command == 'init':
            store.create_event(args.event, args.kind, args.sender, args.budget_xrp,
                               args.payment_limit_xrp, json.loads(args.vendors_file.read_text()))
            result = store.summary(args.event)
        elif args.command == 'propose':
            result = store.propose(args.event, args.vendor, args.invoice, args.amount_xrp)
        elif args.command == 'budget':
            result = store.summary(args.event)
        elif args.command == 'show':
            result = store.get(args.payment_id)
        else:
            if args.command == 'pay':
                from dotenv import load_dotenv
                load_dotenv(Path(__file__).resolve().with_name('.env'), override=False)
            ledger = TestnetLedger()
            result = pay(store, ledger, args.payment_id) if args.command == 'pay' else reconcile(store, ledger, args.payment_id)
        result.pop('signed_json', None)
        if result.get('tx_hash'):
            result['explorer_url'] = f"https://testnet.xrpl.org/transactions/{result['tx_hash']}"
        print(json.dumps(result, indent=2))
    finally:
        store.db.close()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, sqlite3.Error, OSError) as error:
        raise SystemExit(f'Finance operation failed ({type(error).__name__}). Check inputs and saved payment status.') from None
