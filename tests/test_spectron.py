"""Verify Spectron routing, pagination, and exact-content integrity offline."""
import json
import unittest
from dataclasses import asdict
from unittest.mock import Mock, patch

from agent_runtime.runtime import DaytonaOpenCodeRuntime, RuntimeConfig
from document_store import DocumentStore, capture_document
from document_store.spectron import SpectronDocuments


SETTINGS = {'SPECTRON_URL': 'https://memory.example.org',
            'SPECTRON_CONTEXT_ID': 'test', 'SPECTRON_API_KEY': 'test-key'}


class SpectronTests(unittest.TestCase):
    def test_spectron_takes_precedence_and_enables_runtime(self):
        settings = {**SETTINGS, 'SURREAL_URL': 'http://127.0.0.1:8000'}
        store = DocumentStore(env=settings)
        self.assertIsInstance(store.spectron, SpectronDocuments)
        self.assertIsNone(store.memory)
        runtime = DaytonaOpenCodeRuntime(RuntimeConfig('openai/example'), env=SETTINGS)
        self.assertIsInstance(runtime.document_store.spectron, SpectronDocuments)
        with self.assertRaisesRegex(ValueError, 'SPECTRON_CONTEXT_ID'):
            DocumentStore(env={'SPECTRON_URL': SETTINGS['SPECTRON_URL']})

    def test_pagination_continues_after_unrelated_short_page(self):
        backend = SpectronDocuments(SETTINGS)
        key = 'a' * 64
        backend.request = Mock(side_effect=[
            {'documents': [{'id': 'other', 'title': 'Unrelated'}],
             'page': {'nextCursor': 'next/page'}},
            {'documents': [{'id': 'owned', 'title': f'daytona-document:{key} Title'}], 'page': {}}])
        self.assertEqual(backend.find(key)['id'], 'owned')
        self.assertIn('cursor=next%2Fpage', backend.request.call_args.args[0])

    def test_raw_roundtrip_and_tamper_detection(self):
        backend = SpectronDocuments(SETTINGS)
        document = capture_document('https://example.org/report', 'Exact research text 🌎')
        payload = asdict(document)
        payload['retrieved_at'] = document.retrieved_at.isoformat()
        row = {'id': 'remote', 'key': document.key}
        backend.request = Mock(return_value=json.dumps(payload).encode())
        self.assertEqual(backend.read(row)['content'], document.content)
        payload['content'] = 'corrupted'
        backend.request.return_value = json.dumps(payload).encode()
        with self.assertRaisesRegex(RuntimeError, 'checksum'):
            backend.read(row)

    def test_existing_version_does_not_upload_again(self):
        backend = SpectronDocuments(SETTINGS)
        with patch.object(backend, 'find', return_value={'id': 'existing'}), \
                patch.object(backend, 'request') as request:
            self.assertEqual(backend.save({'key': 'existing-key'}), 'existing-key')
        request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
