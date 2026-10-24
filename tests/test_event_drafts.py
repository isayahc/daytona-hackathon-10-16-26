"""Exercise draft validation, durable storage, and the local HTTP interface."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from operator_app.drafts import list_drafts, save_draft
from operator_app.server import Handler


class DraftTests(unittest.TestCase):
    """Verify user-authored records stay separate from fictional fixtures."""

    def setUp(self) -> None:
        """Create an isolated store for each test."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / 'workspace.sqlite3'
        self.payload = {'title': 'Repair day', 'starts_at': '2026-11-14T13:00:00-05:00'}

    def test_round_trip(self) -> None:
        """Drafts retain identity, timezone, unknown metrics, and non-mock provenance."""
        saved = save_draft(self.database, self.payload)
        self.assertEqual(list_drafts(self.database), [saved])
        self.assertFalse(saved['is_mock'])
        self.assertIsNone(saved['funding_secured_usd'])
        self.assertEqual(saved['starts_at'], self.payload['starts_at'])
        self.assertNotEqual(save_draft(self.database, self.payload)['id'], saved['id'])

    def test_invalid_input_does_not_persist(self) -> None:
        """Reject nonfinite money, fractions, naive dates, and malformed strings."""
        for patch in ({'title': ''}, {'title': 12}, {'budget_usd': float('nan')},
                      {'budget_usd': float('inf')}, {'budget_usd': -1},
                      {'registration_target': 1.5}, {'registration_target': True},
                      {'starts_at': '2026-11-14T13:00:00'}, {'summary': []}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                save_draft(self.database, {**self.payload, **patch})
        self.assertEqual(list_drafts(self.database), [])

    def test_http_create_reload_and_cross_origin_rejection(self) -> None:
        """Drive the same endpoints used by the browser without external services."""
        handler = type('TestHandler', (Handler,), {'database': self.database})
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection('127.0.0.1', server.server_port)
            connection.request('POST', '/api/events', json.dumps(self.payload),
                               {'Content-Type': 'application/json'})
            response = connection.getresponse()
            self.assertEqual(response.status, 201)
            saved = json.loads(response.read())
            connection.request('GET', '/api/workspace')
            response = connection.getresponse()
            events = json.loads(response.read())['events']
            self.assertIn(saved, events)
            self.assertTrue(any(event['is_mock'] for event in events))
            connection.request('POST', '/api/events', json.dumps(self.payload),
                               {'Content-Type': 'application/json', 'Origin': 'https://untrusted.example'})
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            self.assertEqual(len(list_drafts(self.database)), 1)
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
