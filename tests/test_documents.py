"""Verify document downloads, original-file fidelity, and automatic research capture."""
from __future__ import annotations
import base64
import hashlib
import json
import sys
import unittest
from email.message import Message
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

import documents
from operator_app.models import Document
from document_store import DocumentStore, capture_document, documents_from_events
from agent_runtime import DaytonaOpenCodeRuntime, RuntimeConfig
from test_agent_runtime import client_fixture, sdk_module


def pdf_fixture() -> bytes:
    """Build an actual PDF with selectable text instead of mocking extraction."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({
        NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 20 100 Td (Climate and energy report) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class RecordingDatabase:
    """A minimal offline store; live SurrealQL semantics need a real DB check."""

    def __init__(self) -> None:
        self.records = {}
        self.blobs = {}
        self.texts = {}
        self.calls = []
        self.fail_blob_position = None

    def query(self, sql, variables=None):
        v = variables or {}
        self.calls.append((sql, v))
        if sql == 'RETURN true;':
            return [True]
        if sql.startswith("SELECT * FROM type::record('document:'"):
            row = self.records.get(v['key'])
            return [[row] if row else []]
        if sql.startswith("UPSERT type::record('document_blob:'"):
            if v['position'] == self.fail_blob_position:
                raise RuntimeError('simulated interrupted upload')
            self.assert_unpadded(v['content'])
            self.blobs[v['chunk_key']] = base64.b64decode(v['content'] + '=' * (-len(v['content']) % 4))
        elif sql.startswith("UPSERT type::record('document_text:'"):
            self.texts[v['chunk_key']] = v['chunk']
        elif sql.startswith("UPSERT type::record('document:'"):
            self.records[v['key']] = v['document']
        elif sql.startswith('SELECT encoding::base64::encode'):
            content = self.blobs.get(v['chunk_key'])
            return [[{'content': base64.b64encode(content).decode().rstrip('=')}] if content is not None else []]
        elif sql.startswith('SELECT text FROM'):
            row = self.texts.get(v['chunk_key'])
            return [[{'text': row['text']}] if row else []]
        else:
            raise AssertionError(f'Unexpected query: {sql}')
        return [None]

    @staticmethod
    def assert_unpadded(content):
        if '=' in content:
            raise AssertionError('SurrealDB 2.x expects unpadded base64')


class DocumentDownloadTests(unittest.TestCase):
    def metadata(self, filename='report.txt', mime='text/plain'):
        return {'source_url': 'https://example.org/' + filename,
                'resolved_url': 'https://example.org/' + filename,
                'source_host': 'example.org', 'filename': filename,
                'content_type': mime, 'charset': 'utf-8',
                'downloaded_at': '2026-10-16T12:00:00+00:00'}

    def test_pdf_text_and_blank_scan_status(self):
        text, info = documents.extract(pdf_fixture(), self.metadata('report.pdf', 'application/pdf'))
        self.assertIn('Climate and energy report', text)
        self.assertEqual(info['extraction_status'], 'extracted')
        self.assertEqual(info['page_count'], 1)
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        blank = BytesIO()
        writer.write(blank)
        text, info = documents.extract(blank.getvalue(), self.metadata('scan.pdf', 'application/pdf'))
        self.assertFalse(text.strip())
        self.assertEqual(info['extraction_status'], 'no_text')

    def test_html_removes_scripts_but_keeps_inline_word_spacing(self):
        data = b'<html><head><title>Hidden</title></head><body><p>Clean <b>energy</b> &amp; climate.</p><script>secret()</script><p>Next.</p></body></html>'
        text, info = documents.extract(data, self.metadata('report.html', 'text/html'))
        self.assertEqual(text, 'Clean energy & climate.\nNext.')
        self.assertEqual(info['extraction_status'], 'extracted')

    def test_unsupported_and_encrypted_files_keep_explicit_status(self):
        text, info = documents.extract(b'\x00\xff', self.metadata('data.bin', 'application/octet-stream'))
        self.assertEqual((text, info['extraction_status']), ('', 'unsupported'))
        reader = PdfReader(BytesIO(pdf_fixture()))
        writer = PdfWriter(clone_from=reader)
        writer.encrypt('password')
        output = BytesIO()
        writer.write(output)
        text, info = documents.extract(output.getvalue(), self.metadata('locked.pdf', 'application/pdf'))
        self.assertEqual((text, info['extraction_status']), ('', 'encrypted'))

    def test_multichunk_roundtrip_dedup_and_integrity(self):
        data = ('Climate 🌎 and energy\n' * 30000).encode()
        db = RecordingDatabase()
        store = documents.Documents(db)
        with patch('documents.download', return_value=(data, self.metadata())):
            record = store.ingest('https://example.org/report.txt', 'climate', 'Test climate report')
            calls = len(db.calls)
            duplicate = store.ingest('https://example.org/report.txt', 'climate')
        self.assertTrue(duplicate['already_stored'])
        self.assertEqual(len(db.calls), calls + 2)
        self.assertGreater(record['blob_chunks'], 1)
        self.assertGreater(record['text_chunks'], 1)
        # All serialized writes stay far below the documented 4 MiB RPC ceiling.
        for sql, variables in db.calls:
            self.assertLess(len(json.dumps({'params': [sql, variables]}).encode()), 512 * 1024)
        with TemporaryDirectory() as tmp:
            original = Path(tmp) / 'original.txt'
            extracted = Path(tmp) / 'extracted.txt'
            store.export(record['key'], original)
            store.export(record['key'], extracted, text=True)
            self.assertEqual(original.read_bytes(), data)
            self.assertEqual(extracted.read_text(), data.decode())
            with self.assertRaisesRegex(ValueError, 'already exists'):
                store.export(record['key'], original)
            db.blobs[f"{record['key']}_0"] = b'corrupt'
            target = Path(tmp) / 'corrupt.txt'
            with self.assertRaisesRegex(ValueError, 'checksum'):
                store.export(record['key'], target)
            self.assertFalse(target.exists())

    def test_interrupted_upload_is_not_published_and_can_be_retried(self):
        data = b'A' * (documents.BLOB_CHUNK_BYTES + 1)
        db = RecordingDatabase()
        store = documents.Documents(db)
        db.fail_blob_position = 1
        with patch('documents.download', return_value=(data, self.metadata())):
            with self.assertRaises(RuntimeError):
                store.ingest('https://example.org/report.txt', 'weather')
            self.assertFalse(db.records)
            db.fail_blob_position = None
            record = store.ingest('https://example.org/report.txt', 'weather')
        self.assertEqual(len(db.records), 1)
        self.assertEqual(record['sha256'], hashlib.sha256(data).hexdigest())

    def test_download_metadata_and_actual_size_limit(self):
        response = MagicMock()
        response.geturl.return_value = 'https://example.org/final.pdf'
        headers = Message()
        headers['Content-Type'] = 'application/pdf'
        headers['Content-Disposition'] = 'attachment; filename="../../report.pdf"'
        response.headers = headers
        response.read.return_value = b'pdf data'
        with patch('documents.urlopen') as open_url:
            open_url.return_value.__enter__.return_value = response
            data, metadata = documents.download('https://example.org/report.pdf#page=1')
            self.assertEqual(data, b'pdf data')
            self.assertEqual(metadata['filename'], 'report.pdf')
            self.assertEqual(metadata['source_url'], 'https://example.org/report.pdf')
            self.assertEqual(metadata['resolved_url'], 'https://example.org/final.pdf')
            self.assertNotIn('Authorization', open_url.call_args.args[0].headers)
            with patch('documents.MAX_DOWNLOAD_BYTES', 4):
                with self.assertRaisesRegex(ValueError, 'limit'):
                    documents.download('https://example.org/report.pdf')

    def test_invalid_source_is_rejected_before_network_access(self):
        for url in ['file:///etc/passwd', 'ftp://example.org/a.pdf', 'https://user:pass@example.org/a.pdf']:
            with patch('documents.urlopen') as network:
                with self.assertRaises(ValueError):
                    documents.download(url)
                network.assert_not_called()

    def test_search_is_parameterized_and_only_reads_published_documents(self):
        db = MagicMock()
        db.query.return_value = [[]]
        documents.Documents(db).search("'; DELETE document; --", 'energy')
        sql, variables = db.query.call_args.args
        self.assertNotIn('DELETE document', sql)
        self.assertIn('SELECT VALUE key FROM document', sql)
        self.assertEqual(variables['category'], 'energy')


def fetch_event(content: str = 'A public grant guide', status: str = 'completed') -> str:
    """Create a fixture matching pinned OpenCode's JSON tool event shape."""
    return json.dumps({'type': 'tool_use', 'sessionID': 'ses_research', 'part': {
        'tool': 'webfetch', 'callID': 'call1', 'state': {'status': status,
        'input': {'url': 'https://example.org/guide#section', 'format': 'markdown'},
        'output': content, 'title': 'Grant guide', 'metadata': {'truncated': False}}}})


class DocumentCaptureTests(unittest.TestCase):
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
