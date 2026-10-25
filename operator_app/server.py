"""Serve the local operator workspace, sample data, and persisted event drafts."""
from __future__ import annotations
import argparse
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from .mock_data import demo_workspace
from .payments import Payments, configured_payments
from .drafts import list_drafts, save_draft
from .chat import ChatService, ChatUnavailable, ChatBusy, targets_for


def encode(value: Any) -> Any:
    """Serialize domain timestamps and enums without losing timezone offsets."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f'Unsupported JSON type: {type(value).__name__}')


def workspace_json() -> bytes:
    """Build the reusable API payload from the domain models."""
    return json.dumps(asdict(demo_workspace()), default=encode).encode('utf-8')


class Handler(SimpleHTTPRequestHandler):
    """Expose static UI assets, sample data, and local event creation."""

    payments: Payments | None = None

    database = Path('.operator/workspace.sqlite3')
    chat: ChatService | None = None

    def workspace(self) -> dict[str, Any]:
        value = json.loads(workspace_json())
        value['events'].extend(list_drafts(self.database))
        return value

    def respond(self, status: int, value: Any) -> None:
        """Send a noncacheable JSON response."""
        payload = json.dumps(value, default=encode).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        """Create a local draft; reject cross-origin and oversized requests."""
        path = urlsplit(self.path).path
        if path.startswith('/api/xrpl/'):
            self.payment_post()
            return
        if path not in {'/api/events', '/api/chat', '/api/message-drafts'}:
            self.respond(404, {'error': 'Unknown endpoint.'})
            return
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host', ''):
            self.respond(403, {'error': 'Cross-origin writes are not allowed.'})
            return
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            self.respond(415, {'error': 'Expected application/json.'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 32_768:
                raise ValueError('Request must be between 1 and 32,768 bytes.')
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, dict):
                raise ValueError('Expected an event object.')
            if path == '/api/events':
                self.respond(201, save_draft(self.database, value))
            elif self.chat is None:
                self.respond(503, {'error': 'Chat is unavailable. Restart the server.'})
            elif path == '/api/message-drafts':
                if not all(isinstance(value.get(key), str) for key in ('run_id', 'draft_id')):
                    raise ValueError('Provide a run and draft ID.')
                self.respond(200, self.chat.edit(value['run_id'], value['draft_id'], value))
            else:
                workspace = self.workspace()
                event = next((e for e in workspace['events'] if e['id'] == value.get('event_id')), None)
                if event is None:
                    raise ValueError('Select an event before asking the agent to draft messages.')
                targets = targets_for(event, workspace, value.get('candidates'))
                self.respond(202, self.chat.start(event, value.get('prompt'), targets))
        except ChatUnavailable as error:
            self.respond(503, {'error': str(error)})
        except ChatBusy as error:
            self.respond(409, {'error': str(error)})
        except (ValueError, UnicodeDecodeError) as error:
            self.respond(400, {'error': str(error)})
        except (OSError, sqlite3.Error):
            self.respond(500, {'error': 'Could not save the draft. Check database permissions.'})

    def _json(self, value: Any, status: int = 200) -> None:
        """Return uncached JSON without disclosing configuration or wallet secrets."""
        payload = json.dumps(value, default=encode).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def payment_post(self) -> None:
        """Accept same-origin local Testnet operations with bounded JSON bodies."""
        path = urlsplit(self.path).path
        if path not in ('/api/xrpl/invoices', '/api/xrpl/pay', '/api/xrpl/reconcile'):
            self._json({'error': 'Unknown endpoint.'}, 404)
            return
        # JSON + custom header prevents cross-origin HTML forms from spending.
        # Validate Host too, to reject DNS rebinding against the local server.
        host = self.headers.get('Host', '')
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        origin = self.headers.get('Origin')
        if (host not in allowed or (origin and origin != f'http://{host}')
                or self.headers.get('X-Operator-Request') != '1'
                or self.headers.get_content_type() != 'application/json'):
            self._json({'error': 'Use the local workspace or same-origin JSON API.'}, 403)
            return
        if self.payments is None:
            self._json({'error': 'Payment service unavailable.'}, 503)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 8192:
                raise ValueError('JSON request must be 1–8192 bytes.')
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError('JSON body must be an object.')
            self.payments.event_ids = {event['id'] for event in self.workspace()['events']}
            if path == '/api/xrpl/invoices':
                result = self.payments.create(payload)
            else:
                invoice_id = payload.get('invoice_id')
                if not isinstance(invoice_id, str):
                    raise ValueError('Provide an invoice_id.')
                if path == '/api/xrpl/pay':
                    result = self.payments.pay(invoice_id)
                else:
                    result = self.payments.reconcile(invoice_id, payload.get('tx_hash'))
            self._json(result)
        except (ValueError, UnicodeError) as exc:
            self._json({'error': str(exc)}, 400)
        except Exception:
            self._json({'error': 'Testnet unavailable. Refresh invoices and reconcile any pending transaction; do not create a replacement payment.'}, 502)

    def do_GET(self) -> None:
        """Combine saved drafts with fixtures and serve the static application."""
        if urlsplit(self.path).path == '/api/xrpl':
            if self.payments is not None:
                self.payments.event_ids = {event['id'] for event in self.workspace()['events']}
            self._json(self.payments.snapshot() if self.payments else {'enabled': False, 'network': 'testnet'})
        elif urlsplit(self.path).path == '/api/chat':
            event_id = parse_qs(urlsplit(self.path).query).get('event_id', [''])[0]
            if self.chat is None:
                self.respond(503, {'error': 'Chat is unavailable. Restart the server.'})
            else:
                self.respond(200, {'runs': self.chat.history(event_id)})
        elif urlsplit(self.path).path == '/api/workspace':
            value = self.workspace()
            payload = json.dumps(value).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(payload)
        else:
            super().do_GET()


def main() -> None:
    """Start a loopback-only local development server."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--database', type=Path, default=Handler.database, help='Local SQLite draft store')
    args = parser.parse_args()
    try:
        from dotenv import load_dotenv
    except ImportError:
        pass  # The local workspace remains usable without optional dependencies.
    else:
        load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    Handler.payments = configured_payments(
        {event.id for event in demo_workspace().events}
        | {event['id'] for event in list_drafts(args.database)}
    )
    Handler.database = args.database
    Handler.chat = ChatService(args.database)
    static = Path(__file__).parent / 'static'
    handler = partial(Handler, directory=str(static))
    with ThreadingHTTPServer(('127.0.0.1', args.port), handler) as server:
        print(f'Operator workspace: http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
