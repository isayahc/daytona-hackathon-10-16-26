"""Serve the independent XRPL Testnet ticket checkout locally."""
from __future__ import annotations

import argparse
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .event_tickets import DEFAULT_TICKETS_DB

STATIC_DIR = Path(__file__).resolve().with_name('static')


class Handler(SimpleHTTPRequestHandler):
    """Serve only ticket assets and APIs, independently of the main application."""

    def __init__(self, *args: Any, tickets_db: Path = DEFAULT_TICKETS_DB, **kwargs: Any) -> None:
        self.tickets_db = tickets_db
        kwargs.setdefault('directory', str(STATIC_DIR))
        super().__init__(*args, **kwargs)

    def json_response(self, code: int, value: Any) -> None:
        payload = json.dumps(value).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(payload)

    def ticket_request(self, method: str, path: str) -> None:
        """Local demo only; reject foreign origins/hosts and oversized input."""
        port = self.server.server_port
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if self.headers.get('Host') not in hosts or self.headers.get('Origin') not in (
                None, *(f'http://{host}' for host in hosts)):
            self.json_response(403, {'error': 'Checkout is available only from this local server.'})
            return
        from .event_tickets import TicketError, TicketLedger, TicketStore
        store = None
        try:
            body = {}
            if method == 'POST':
                if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                    self.json_response(415, {'error': 'Use a JSON request.'})
                    return
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    self.close_connection = True
                    self.json_response(413, {'error': 'Request size must be between 1 and 4096 bytes.'})
                    return
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict) or not all(isinstance(v, str) for v in body.values()):
                    raise TicketError('Provide text values for the checkout fields.')
            store = TicketStore(self.tickets_db)
            if path.startswith('/api/tickets/xaman/'):
                from .xaman import XamanClient, XamanFlow, credentials
                if method == 'GET' and path == '/api/tickets/xaman/config':
                    result = {'enabled': all(credentials()), 'network': 'testnet'}
                else:
                    flow = XamanFlow(store, XamanClient())
                    if method == 'POST' and path == '/api/tickets/xaman/connect':
                        result = flow.create('connect')
                    elif method == 'POST' and path == '/api/tickets/xaman/pay':
                        result = flow.create('payment', connection_id=body['connection_id'], order_id=body['order_id'])
                    elif method == 'POST' and path == '/api/tickets/xaman/status':
                        result = flow.status(body['request_id'], TicketLedger())
                    else:
                        self.json_response(404, {'error': 'Wallet route not found.'})
                        return
            elif method == 'GET' and path == '/api/tickets/events':
                result = {'events': store.events(), 'network': 'testnet'}
            elif method == 'GET' and path.startswith('/api/tickets/orders/'):
                result = store.order(path.removeprefix('/api/tickets/orders/'))
            elif method == 'POST' and path == '/api/tickets/orders':
                from .event_finance import address
                buyer = body.get('buyer', '')
                if body.get('connection_id'):
                    from .xaman import XamanClient, XamanFlow
                    buyer = XamanFlow(store, XamanClient()).account(body['connection_id'])
                address(buyer)
                event = store.event(body['event_id'])
                if event['available'] <= 0:
                    raise TicketError('All tickets are sold or reserved.')
                result = store.checkout(body['event_id'], buyer, TicketLedger().validated_index())
            elif method == 'POST' and path == '/api/tickets/verify':
                result = store.verify(TicketLedger(), body['order_id'], body['tx_hash'])
            else:
                self.json_response(404, {'error': 'Checkout route not found.'})
                return
            self.json_response(200, result)
        except TicketError as error:
            self.json_response(400, {'error': str(error)})
        except (ValueError, KeyError, TypeError):
            self.json_response(400, {'error': 'Check the request fields and use a valid classic XRPL wallet address.'})
        except Exception:
            self.json_response(503, {'error': 'Could not reach the ledger or order store. Retry verification before paying again.'})
        finally:
            if store is not None:
                store.db.close()

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith('/api/tickets/'):
            self.ticket_request('GET', path)
        elif path in ('/', '/tickets', '/tickets.html', '/tickets.js', '/tickets.css'):
            self.path = '/tickets.html' if path in ('/', '/tickets') else path
            super().do_GET()
        else:
            self.json_response(404, {'error': 'Route not found.'})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith('/api/tickets/'):
            self.ticket_request('POST', path)
        else:
            self.json_response(404, {'error': 'Route not found.'})

    def list_directory(self, path: str) -> None:
        self.send_error(404, 'Route not found')
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8081)
    parser.add_argument('--tickets-db', type=Path, default=DEFAULT_TICKETS_DB,
                        help='Ticket database (defaults to xrpltest/event-tickets.sqlite3)')
    args = parser.parse_args()
    handler = partial(Handler, tickets_db=args.tickets_db)
    with ThreadingHTTPServer(('127.0.0.1', args.port), handler) as server:
        print(f'XRPL Testnet tickets: http://127.0.0.1:{server.server_port}/tickets', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
