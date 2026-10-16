"""Opt-in round trips through a disposable real SurrealDB and a local HTTP source.

Run with SURREAL_TEST_BINARY=/path/to/surreal; no user database or .env is used.
"""
import os
import socket
import subprocess
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import URLError
from urllib.request import urlopen
from unittest.mock import patch

from documents import Documents
from document_store import DocumentStore, capture_document
from outreach import Memory


TEXT = 'Weather and climate: renewable energy. 🌎\n'.encode()
# Larger than the HTTP RPC request limit: this must use multiple bounded writes.
BINARY = bytes(range(256)) * (5 * 1024 * 4)


class SourceHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = BINARY if self.path == '/original.bin' else TEXT
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream' if self.path == '/original.bin'
                         else 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get('SURREAL_TEST_BINARY'), 'Set SURREAL_TEST_BINARY for real DB checks')
class DocumentIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        cls.database_url = f'http://127.0.0.1:{port}'
        cls.process = subprocess.Popen(
            [os.environ['SURREAL_TEST_BINARY'], 'start', '--bind', f'127.0.0.1:{port}',
             '--user', 'root', '--pass', 'integration-only', 'memory'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_database)
        for _ in range(100):
            try:
                with urlopen(cls.database_url + '/health', timeout=1):
                    break
            except (URLError, TimeoutError):
                if cls.process.poll() is not None:
                    raise RuntimeError('Disposable SurrealDB exited before becoming ready')
                time.sleep(0.1)
        else:
            raise RuntimeError('Disposable SurrealDB did not become ready')
        cls.source = ThreadingHTTPServer(('127.0.0.1', 0), SourceHandler)
        cls.source_url = f'http://127.0.0.1:{cls.source.server_port}'
        cls.thread = threading.Thread(target=cls.source.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.source.server_close)
        cls.addClassCleanup(cls.source.shutdown)

    @classmethod
    def stop_database(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=10)

    def setUp(self):
        settings = {'SURREAL_URL': self.database_url, 'SURREAL_USER': 'root',
                    'SURREAL_PASS': 'integration-only', 'SURREAL_TOKEN': '',
                    'SURREAL_NS': 'document_tests', 'SURREAL_DB': 'document_tests'}
        environment = patch.dict(os.environ, settings)
        environment.start()
        self.addCleanup(environment.stop)
        self.db = Memory()
        self.store = Documents(self.db)

    def test_download_store_search_and_export_text(self):
        record = self.store.ingest(self.source_url + '/report.txt', 'climate', 'Integration report')
        self.assertEqual(record['extraction_status'], 'extracted')
        self.assertTrue(self.store.ingest(self.source_url + '/report.txt', 'climate')['already_stored'])
        self.assertIn(record['key'], [row['key'] for row in self.store.list()])
        self.assertIn(record['key'], [row['key'] for row in self.store.list('climate')])
        self.assertFalse(self.store.list('defense'))
        hits = self.store.search('RENEWABLE ENERGY', 'climate')
        self.assertEqual(hits[0]['document_key'], record['key'])
        self.assertFalse(self.store.search('renewable', 'defense'))
        with TemporaryDirectory() as tmp:
            original = Path(tmp) / 'original.txt'
            extracted = Path(tmp) / 'extracted.txt'
            self.store.export(record['key'], original)
            self.store.export(record['key'], extracted, text=True)
            self.assertEqual(original.read_bytes(), TEXT)
            self.assertEqual(extracted.read_bytes(), TEXT)

    def test_original_larger_than_rpc_limit_roundtrips(self):
        record = self.store.ingest(self.source_url + '/original.bin', 'energy')
        self.assertGreater(record['size_bytes'], 4 * 1024 * 1024)
        self.assertEqual(record['extraction_status'], 'unsupported')
        with TemporaryDirectory() as tmp:
            original = Path(tmp) / 'original.bin'
            self.store.export(record['key'], original)
            self.assertEqual(original.read_bytes(), BINARY)

    def test_downloads_and_runtime_text_coexist_in_the_same_database(self):
        text_store = DocumentStore(memory=self.db)
        captured = capture_document('https://example.org/coexist', 'Agent retrieved climate research')
        text_store.save(captured)
        downloaded = self.store.ingest(self.source_url + '/coexist.txt', 'weather')
        download_keys = [row['key'] for row in self.store.list()]
        capture_keys = [row['key'] for row in text_store.list()]
        self.assertIn(downloaded['key'], download_keys)
        self.assertNotIn(captured.key, download_keys)
        self.assertIn(captured.key, capture_keys)
        self.assertNotIn(downloaded['key'], capture_keys)
        self.assertEqual(text_store.get(captured.key)[0]['content'], captured.content)
        self.assertFalse(text_store.get(downloaded['key']))
        with self.assertRaisesRegex(ValueError, 'retrieved-text record'):
            self.store.get(captured.key)
