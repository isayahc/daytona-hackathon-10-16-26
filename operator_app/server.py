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

    def do_GET(self) -> None:
        """Route the mock API; delegate static file handling to the standard library."""
        if urlsplit(self.path).path == '/api/workspace':
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
