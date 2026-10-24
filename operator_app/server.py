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
from urllib.parse import urlsplit
from .mock_data import demo_workspace
from .drafts import list_drafts, save_draft


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

    database = Path('.operator/workspace.sqlite3')

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
        if urlsplit(self.path).path != '/api/events':
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
            self.respond(201, save_draft(self.database, value))
        except (ValueError, UnicodeDecodeError) as error:
            self.respond(400, {'error': str(error)})
        except (OSError, sqlite3.Error):
            self.respond(500, {'error': 'Could not save the draft. Check database permissions.'})

    def do_GET(self) -> None:
        """Combine saved drafts with fixtures and serve the static application."""
        if urlsplit(self.path).path == '/api/workspace':
            value = json.loads(workspace_json())
            value['events'].extend(list_drafts(self.database))
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
    Handler.database = args.database
    static = Path(__file__).parent / 'static'
    handler = partial(Handler, directory=str(static))
    with ThreadingHTTPServer(('127.0.0.1', args.port), handler) as server:
        print(f'Operator workspace: http://127.0.0.1:{args.port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()

