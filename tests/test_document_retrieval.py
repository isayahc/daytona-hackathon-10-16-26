"""Exercise extraction, topic filtering, and source injection into agent turns."""
import json
import sys
import unittest
from dataclasses import asdict, replace
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

from agent_runtime.runtime import DaytonaOpenCodeRuntime, RuntimeConfig
from document_store import DocumentStore, capture_document
from document_store.ingest import ingest_document
from test_agent_runtime import client_fixture, sdk_module
from test_documents import pdf_fixture


class RetrievalTests(unittest.TestCase):
    def test_real_pdf_and_word_extraction(self):
        store = MagicMock()
        store.save.side_effect = lambda document: document.key
        word = BytesIO()
        with ZipFile(word, 'w') as archive:
            archive.writestr('word/document.xml',
                             '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                             '<w:body><w:p><w:r><w:t>Community solar energy</w:t></w:r></w:p></w:body></w:document>')
        with TemporaryDirectory() as directory:
            for filename, data, expected in [('report.pdf', pdf_fixture(), 'Climate and energy report'),
                                              ('report.docx', word.getvalue(), 'Community solar energy')]:
                path = Path(directory) / filename
                path.write_bytes(data)
                ingest_document(store, source_url='https://example.org/' + filename,
                                file=path, category='energy')
                document = store.save.call_args.args[0]
                self.assertIn(expected, document.content)
                self.assertEqual(document.category, 'energy')

    def test_failed_extraction_never_saves(self):
        store = MagicMock()
        with patch('document_store.ingest.download', return_value=(b'unreadable', {
                'filename': 'bad.pdf', 'content_type': 'application/pdf', 'charset': 'utf-8'})):
            with self.assertRaisesRegex(ValueError, 'failed'):
                ingest_document(store, source_url='https://example.org/bad.pdf')
        store.save.assert_not_called()

    def test_search_matches_late_passages_and_topic_filter(self):
        store = DocumentStore(memory=MagicMock())
        energy = replace(capture_document('https://example.org/energy',
                         'Unrelated introduction. ' * 300 + 'Community solar lowers energy costs.'), category='energy')
        weather = replace(capture_document('https://example.org/weather', 'Solar heat safety.'), category='weather')
        store.list = MagicMock(return_value=[{'key': energy.key}, {'key': weather.key}])
        documents = {document.key: asdict(document) for document in (energy, weather)}
        store.get = lambda key: [documents[key]]
        hits = store.search('community solar energy', category='energy')
        self.assertTrue(hits)
        self.assertTrue(all(hit['document_key'] == energy.key for hit in hits))
        self.assertGreater(hits[0]['offset'], 0)
        self.assertEqual(store.search('no_matching_vocabulary'), [])
        with self.assertRaises(ValueError):
            store.search('solar', limit=1000)

    def test_agent_receives_bounded_evidence_and_returns_citation_map(self):
        client = client_fixture()
        hit = {'document_key': 'doc-key', 'source_url': 'https://example.org/solar',
               'title': 'Solar report', 'passage': 'Community solar can reduce energy bills.'}
        output = json.dumps({'type': 'text', 'sessionID': 'test', 'part': {'text': 'Supported answer [D1]'}})
        with patch.dict(sys.modules, {'daytona': sdk_module()}):
            with DaytonaOpenCodeRuntime(RuntimeConfig('openai/example', document_category='energy'),
                                       client=client, env={}) as runtime:
                runtime.document_store = MagicMock()
                runtime.document_store.search.return_value = [hit]
                runtime.document_store.ingest_events.return_value = ()
                client.create.return_value.process.exec.return_value.result = output
                result = runtime.run('How can community solar help?')
                runtime.document_store.search.assert_called_once_with(
                    'How can community solar help?', category='energy', limit=5)
        requests = [json.loads(call.args[0]) for call in client.create.return_value.fs.upload_file.call_args_list
                    if call.args[1].endswith('/request.json')]
        self.assertIn('untrusted source data', requests[0]['prompt'])
        self.assertIn(hit['passage'], requests[0]['prompt'])
        self.assertEqual(result.retrieved_sources[0]['citation'], 'D1')
        self.assertEqual(result.retrieved_sources[0]['source_url'], hit['source_url'])


if __name__ == '__main__':
    unittest.main()
