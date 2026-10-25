"""Attendee checkout and ledger-verified event tickets on XRPL Testnet."""
from __future__ import annotations

import argparse
import json
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .event_finance import TESTNET_URL, address, drops


DEFAULT_TICKETS_DB = Path(__file__).resolve().with_name('event-tickets.sqlite3')


class TicketError(ValueError):
    """An actionable checkout error safe to show to an attendee."""


def xrp_text(amount: int) -> str:
    """Human-readable XRP without floating-point rounding, including in browsers."""
    whole, fraction = divmod(amount, 1_000_000)
    return f'{whole}.{fraction:06d}'.rstrip('0').rstrip('.')


class TicketLedger:
    """Read-only Testnet client. No seeds, signing, or transaction submission."""

    def __init__(self) -> None:
        from xrpl.clients import JsonRpcClient
        self.client = JsonRpcClient(TESTNET_URL)

    def validated_index(self) -> int:
        from xrpl.models.requests import Ledger
        result = self.client.request(Ledger(ledger_index='validated')).result
        index = result.get('ledger_index')
        if result.get('validated') is not True or type(index) is not int or index <= 0:
            raise TicketError('Could not obtain a validated ledger. Try checkout again shortly.')
        return index

    def lookup(self, tx_hash: str) -> dict[str, Any]:
        from xrpl.models.requests import Tx
        return self.client.request(Tx(transaction=tx_hash)).result


class TicketStore:
    """Reserve one seat per order and issue a ticket only once per payment."""

    def __init__(self, path: str | Path) -> None:
        self.db = sqlite3.connect(path, timeout=15, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS ticket_event (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL,
                receiver TEXT NOT NULL, price_drops INTEGER NOT NULL, capacity INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ticket_order (
                id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES ticket_event(id),
                buyer TEXT NOT NULL, destination_tag INTEGER NOT NULL UNIQUE,
                after_ledger INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'awaiting_payment',
                tx_hash TEXT UNIQUE, ledger_index INTEGER, ticket_code TEXT UNIQUE,
                checked_in INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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

    def create_event(self, event_id: str, title: str, kind: str, receiver: str,
                     price_xrp: str, capacity: int) -> dict[str, Any]:
        if not isinstance(event_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', event_id):
            raise TicketError('Event ID must contain 1–80 letters, numbers, hyphens, or underscores.')
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
            raise TicketError('Provide an event title of 1–200 characters.')
        if kind not in ('cultural', 'corporate'):
            raise TicketError('Choose cultural or corporate.')
        if type(capacity) is not int or not 1 <= capacity <= 1_000_000:
            raise TicketError('Capacity must be a positive integer up to one million.')
        address(receiver)
        amount = drops(price_xrp)
        try:
            self.db.execute('INSERT INTO ticket_event VALUES (?, ?, ?, ?, ?, ?)',
                            (event_id, title.strip(), kind, receiver, amount, capacity))
        except sqlite3.IntegrityError:
            raise TicketError('An event with that ID already exists.') from None
        return self.event(event_id)

    def event(self, event_id: str) -> dict[str, Any]:
        row = self.db.execute('''SELECT e.*, COUNT(o.id) AS reserved,
            COALESCE(SUM(o.status='paid'),0) AS tickets_sold
            FROM ticket_event e LEFT JOIN ticket_order o ON o.event_id=e.id
            WHERE e.id=? GROUP BY e.id''', (event_id,)).fetchone()
        if row is None:
            raise TicketError('Event not found.')
        result = dict(row)
        result.update(network='testnet', available=result['capacity'] - result['reserved'])
        result['price_xrp'] = xrp_text(result['price_drops'])
        return result

    def events(self) -> list[dict[str, Any]]:
        return [self.event(row['id']) for row in self.db.execute('SELECT id FROM ticket_event ORDER BY rowid')]

    def order(self, order_id: str) -> dict[str, Any]:
        row = self.db.execute('''SELECT o.*, e.title, e.kind, e.receiver, e.price_drops
            FROM ticket_order o JOIN ticket_event e ON e.id=o.event_id WHERE o.id=?''', (order_id,)).fetchone()
        if row is None:
            raise TicketError('Order not found.')
        result = dict(row)
        result['network'] = 'testnet'
        result['price_xrp'] = xrp_text(result['price_drops'])
        result['payment_request'] = {'TransactionType': 'Payment', 'Account': result['buyer'],
            'Destination': result['receiver'], 'DestinationTag': result['destination_tag'],
            'Amount': str(result['price_drops'])}
        if result['tx_hash']:
            result['explorer_url'] = f"https://testnet.xrpl.org/transactions/{result['tx_hash']}"
        return result

    def checkout(self, event_id: str, buyer: str, after_ledger: int) -> dict[str, Any]:
        address(buyer)
        if type(after_ledger) is not int or after_ledger <= 0:
            raise TicketError('Checkout requires a validated ledger index.')
        order_id = str(uuid.uuid4())
        with self.atomic():
            event = self.event(event_id)
            if event['available'] <= 0:
                raise TicketError('All tickets are sold or reserved.')
            if buyer == event['receiver']:
                raise TicketError('Use an attendee wallet different from the organizer wallet.')
            for _ in range(20):
                tag = secrets.randbelow(2**32 - 1) + 1
                if not self.db.execute('SELECT 1 FROM ticket_order WHERE destination_tag=?', (tag,)).fetchone():
                    break
            else:
                raise TicketError('Could not allocate a payment reference. Try again.')
            self.db.execute('''INSERT INTO ticket_order
                (id, event_id, buyer, destination_tag, after_ledger) VALUES (?, ?, ?, ?, ?)''',
                (order_id, event_id, buyer, tag, after_ledger))
        return self.order(order_id)

    def verify(self, ledger: Any, order_id: str, tx_hash: str) -> dict[str, Any]:
        if not isinstance(tx_hash, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', tx_hash):
            raise TicketError('Provide the 64-character hexadecimal transaction hash.')
        tx_hash = tx_hash.upper()
        order = self.order(order_id)
        if order['status'] == 'paid':
            if order['tx_hash'] != tx_hash:
                raise TicketError('This order already has a different confirmed payment.')
            return order
        result = ledger.lookup(tx_hash)
        if not isinstance(result, dict) or result.get('validated') is not True:
            raise TicketError('Payment is not yet validated on Testnet. Check the hash and try again; do not pay again.')
        tx, meta = result.get('tx_json', result), result.get('meta')
        if not isinstance(tx, dict) or not isinstance(meta, dict):
            raise TicketError('The ledger response is missing payment evidence.')
        if result.get('hash', tx.get('hash')) != tx_hash:
            raise TicketError('The ledger returned a different transaction.')
        index = result.get('ledger_index')
        if type(index) is not int or index <= order['after_ledger']:
            raise TicketError('This payment predates checkout. It cannot be used for this order.')
        if meta.get('TransactionResult') != 'tesSUCCESS':
            raise TicketError('The transaction did not succeed. No ticket was issued.')
        if tx.get('TransactionType') != 'Payment':
            raise TicketError('A ticket requires a direct XRP payment.')
        if tx.get('Account') != order['buyer'] or tx.get('Destination') != order['receiver']:
            raise TicketError('Payment sender or recipient does not match this order.')
        if type(tx.get('DestinationTag')) is not int or tx['DestinationTag'] != order['destination_tag']:
            raise TicketError('Payment destination tag does not match this order.')
        # Credit actual delivery, never just the requested Amount/DeliverMax.
        # This MVP accepts only direct, exact native XRP payments, not partial/token/path payments.
        flags = tx.get('Flags', 0)
        if type(flags) is not int or flags & 0x00020000 or tx.get('Paths') or tx.get('SendMax') is not None:
            raise TicketError('Partial or cross-currency payments are not supported for tickets.')
        amount = str(order['price_drops'])
        if tx.get('Amount', tx.get('DeliverMax')) != amount or meta.get('delivered_amount') != amount:
            raise TicketError('The delivered XRP amount does not exactly match the ticket price. Contact the organizer.')
        with self.atomic():
            current = self.order(order_id)
            if current['status'] == 'paid':
                if current['tx_hash'] != tx_hash:
                    raise TicketError('This order already has a different confirmed payment.')
                return current
            if self.db.execute('SELECT 1 FROM ticket_order WHERE tx_hash=?', (tx_hash,)).fetchone():
                raise TicketError('This payment has already been used for another ticket.')
            self.db.execute('''UPDATE ticket_order SET status='paid', tx_hash=?, ledger_index=?, ticket_code=?
                WHERE id=?''', (tx_hash, index, secrets.token_urlsafe(24), order_id))
        return self.order(order_id)

    def check_in(self, ticket_code: str) -> dict[str, Any]:
        with self.atomic():
            row = self.db.execute("SELECT id, checked_in FROM ticket_order WHERE ticket_code=? AND status='paid'",
                                  (ticket_code,)).fetchone()
            if row is None:
                raise TicketError('Ticket not found or unpaid.')
            if row['checked_in']:
                raise TicketError('This ticket has already been checked in.')
            self.db.execute('UPDATE ticket_order SET checked_in=1 WHERE id=?', (row['id'],))
        return self.order(row['id'])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_TICKETS_DB)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init', help='Organizer: set the event, ticket price, capacity, and receiving wallet')
    for field in ('event', 'title', 'receiver', 'price-xrp'):
        init.add_argument('--' + field, required=True)
    init.add_argument('--kind', choices=['cultural', 'corporate'], required=True)
    init.add_argument('--capacity', type=int, required=True)
    checkout = commands.add_parser('checkout')
    checkout.add_argument('--event', required=True)
    checkout.add_argument('--buyer', required=True)
    commands.add_parser('show').add_argument('order_id')
    verify = commands.add_parser('verify')
    verify.add_argument('order_id')
    verify.add_argument('--tx-hash', required=True)
    commands.add_parser('check-in').add_argument('ticket_code')
    commands.add_parser('events')
    args = parser.parse_args()
    store = TicketStore(args.db)
    try:
        if args.command == 'init':
            result = store.create_event(args.event, args.title, args.kind, args.receiver, args.price_xrp, args.capacity)
        elif args.command == 'checkout':
            result = store.checkout(args.event, args.buyer, TicketLedger().validated_index())
        elif args.command == 'verify':
            result = store.verify(TicketLedger(), args.order_id, args.tx_hash)
        elif args.command == 'show':
            result = store.order(args.order_id)
        elif args.command == 'check-in':
            result = store.check_in(args.ticket_code)
        else:
            result = store.events()
        print(json.dumps(result, indent=2))
    finally:
        store.db.close()


if __name__ == '__main__':
    try:
        main()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except Exception:
        raise SystemExit('Ticket operation failed. Check network access and your saved order before retrying.') from None
