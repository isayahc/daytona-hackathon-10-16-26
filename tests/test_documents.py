"""Document provenance, idempotence, runtime ingestion, and failure diagnostics."""
from __future__ import annotations
import json
import unittest
from unittest.mock import MagicMock, patch
from operator_app.models import Document
from document_store import DocumentStore, capture_document, documents_from_events
from agent_runtime import DaytonaOpenCodeRuntime, RuntimeConfig
from test_agent_runtime import client_fixture, sdk_module
import sys


def fetch_event(content: str = 'A public grant guide', status: str = 'completed') -> str:
    """Create a fixture matching pinned OpenCode's JSON tool event shape."""
    return json.dumps({'type': 'tool_use', 'sessionID': 'ses_research', 'part': {
        'tool': 'webfetch', 'callID': 'call1', 'state': {'status': status,
        'input': {'url': 'https://example.org/guide#section', 'format': 'markdown'},
        'output': content, 'title': 'Grant guide', 'metadata': {'truncated': False}}}})


class DocumentTests(unittest.TestCase):
    """Verify only retrieved source text is persisted with source/version provenance."""

    def test_idempotent_versions(self) -> None:
        """Repeated content at one source deduplicates; changed content preserves a new version."""
        first = capture_document('https://example.org/guide#a', 'First')
        same = capture_document('https://example.org/guide#b', 'First')
        changed = capture_document('https://example.org/guide', 'Second')
        self.assertIsInstance(first, Document)
        self.assertEqual(first.key, same.key)
        self.assertNotEqual(first.key, changed.key)
        self.assertEqual(len(first.content_sha256), 64)
        self.assertIsNotNone(first.retrieved_at.tzinfo)

    def test_capture_completed_fetches_only(self) -> None:
        """Unretrieved links, failed tools, and other tool outputs are not source documents."""
        documents = documents_from_events(fetch_event() + '\n' + fetch_event())
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].source_url, 'https://example.org/guide')
        self.assertEqual(documents[0].source_session_id, 'ses_research')
        self.assertEqual(documents[0].capture_method, 'opencode.webfetch')
        self.assertEqual(documents_from_events(fetch_event(status='error')), [])
        self.assertEqual(documents_from_events(json.dumps({'type': 'text', 'part': {'text': 'https://example.org'}})), [])
        self.assertEqual(documents_from_events(fetch_event().replace('webfetch', 'bash')), [])

    def test_invalid_and_oversized_content(self) -> None:
        """Never silently accept empty, invalid, or oversized source documents."""
        for url, content in [('file:///etc/passwd', 'x'), ('https://user:pass@example.org', 'x'),
                             ('https://example.org', ''), ('https://example.org', 'x' * (2*1024*1024+1))]:
            with self.assertRaises(ValueError):
                capture_document(url, content)

    def test_parameterized_upsert(self) -> None:
        """Document contents remain query data, and stored payload retains exact text."""
        memory = MagicMock()
        document = capture_document('https://example.org', "O'Brien; DROP TABLE draft;")
        store = DocumentStore(memory=memory)
        self.assertEqual(store.save(document), document.key)
        query, variables = memory.query.call_args.args
        self.assertNotIn(document.content, query)
        self.assertEqual(variables['document']['content'], document.content)
        self.assertEqual(variables['id'], document.key)
        self.assertIn('UPSERT', query)

    def test_backend_failure_retains_cause(self) -> None:
        """A failed write includes document identity and chains the original failure."""
        memory = MagicMock()
        memory.query.side_effect = ConnectionError('Database unavailable')
        with self.assertRaises(RuntimeError) as error:
            DocumentStore(memory=memory).ingest_events(fetch_event())
        self.assertIn('Document ingestion failed for version', str(error.exception))
        self.assertIsInstance(error.exception.__cause__, ConnectionError)

    def test_runtime_stores_fetches_before_final_parse(self) -> None:
        """Save successful document retrievals even when the turn later reports an error."""
        client = client_fixture()
        store = MagicMock()
        output = fetch_event() + '\n' + '{"type":"error"}'
        with patch.dict(sys.modules, {'daytona': sdk_module()}):
            with self.assertRaises(RuntimeError):
                with DaytonaOpenCodeRuntime(RuntimeConfig('openai/example'), client=client, env={}) as runtime:
                    runtime.document_store = store
                    client.create.return_value.process.exec.return_value.result = output
                    runtime.run('Research')
        store.ingest_events.assert_called_once_with(output)
        client.delete.assert_called_once()

    def test_runtime_reports_saved_document_ids(self) -> None:
        """The caller receives reusable document references, not an unverified save claim."""
        client = client_fixture()
        with patch.dict(sys.modules, {'daytona': sdk_module()}):
            with DaytonaOpenCodeRuntime(RuntimeConfig('openai/example'), client=client, env={}) as runtime:
                runtime.document_store = MagicMock()
                runtime.document_store.ingest_events.return_value = ('doc-key',)
                client.create.return_value.process.exec.return_value.result = json.dumps({
                    'type': 'text', 'sessionID': 'ses_one', 'part': {'text': 'Done'}})
                result = runtime.run('Research')
                self.assertEqual(result.document_keys, ('doc-key',))
                self.assertEqual(result.document_storage, 'saved')

    def test_database_failure_propagates_through_runtime(self) -> None:
        """An ingestion error must prevent a successful agent result and release the sandbox."""
        client = client_fixture()
        with patch.dict(sys.modules, {'daytona': sdk_module()}):
            with self.assertRaisesRegex(ConnectionError, 'Database unavailable'):
                with DaytonaOpenCodeRuntime(RuntimeConfig('openai/example'), client=client, env={}) as runtime:
                    runtime.document_store = MagicMock()
                    runtime.document_store.ingest_events.side_effect = ConnectionError('Database unavailable')
                    client.create.return_value.process.exec.return_value.result = fetch_event()
                    runtime.run('Research')
        client.delete.assert_called_once()

    def test_configured_database_enables_capture(self) -> None:
        """Construct the store automatically using host-only database settings."""
        env = {'SURREAL_URL': 'https://example.surreal.cloud', 'SURREAL_TOKEN': 'private'}
        with patch('document_store.DocumentStore') as store:
            runtime = DaytonaOpenCodeRuntime(RuntimeConfig('openai/example'), client=client_fixture(), env=env)
            self.assertIs(runtime.document_store, store.return_value)
            store.assert_called_once_with(env=env)


if __name__ == '__main__':
    unittest.main()
