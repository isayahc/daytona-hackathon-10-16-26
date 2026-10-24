"""Serve the local UI skeleton and read-only typed mock API."""
from __future__ import annotations
import argparse
import json
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from .mock_data import demo_workspace
from .payments import Payments, configured_payments


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
    """Expose static UI assets and a read-only sample workspace endpoint."""

    payments: Payments | None = None

    def _json(self, value: Any, status: int = 200) -> None:
        """Return uncached JSON without disclosing configuration or wallet secrets."""
        payload = json.dumps(value, default=encode).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
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
        """Route the mock API; delegate static file handling to the standard library."""
        if urlsplit(self.path).path == '/api/xrpl':
            self._json(self.payments.snapshot() if self.payments else {'enabled': False, 'network': 'testnet'})
        elif urlsplit(self.path).path == '/api/workspace':
            payload = workspace_json()
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
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    Handler.payments = configured_payments({event.id for event in demo_workspace().events})
    static = Path(__file__).parent / 'static'
    handler = partial(Handler, directory=str(static))
    with ThreadingHTTPServer(('127.0.0.1', args.port), handler) as server:
        print(f'Operator workspace: http://127.0.0.1:{args.port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            Handler.payments.close()


if __name__ == '__main__':
    main()
