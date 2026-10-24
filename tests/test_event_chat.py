"""Agent chat contract, persistence and HTTP routing without paid services."""
import json
import tempfile
import threading
import time
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from operator_app.chat import ChatBusy, ChatService, ChatUnavailable, parse_drafts, targets_for
from operator_app.server import Handler, workspace_json


def result_for(targets, **overrides):
    return dict(reply='Prepared messages for your event.', drafts=[
        dict(target_id=t['id'], subject='Event invitation', body='Could you share availability?')
        for t in targets], **overrides)


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'workspace.sqlite3'
        self.workspace = json.loads(workspace_json())
        self.event = self.workspace['events'][0]
        self.targets = targets_for(self.event, self.workspace)

    def service(self, generator=None, configure=lambda: None):
        return ChatService(self.database, configure=configure,
                           generator=generator or (lambda prompt, event, targets, history, config:
                                                  parse_drafts(json.dumps(result_for(targets)), targets)))

    def wait(self, service):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            runs = service.history(self.event['id'])
            if runs and runs[-1]['status'] != 'running':
                return runs[-1]
            time.sleep(.01)
        self.fail('Worker did not finish')

    def test_persistence_edits_and_event_isolation(self):
        service = self.service()
        service.start(self.event, 'Organize a repair day', self.targets)
        run = self.wait(service)
        self.assertEqual(run['status'], 'completed')
        self.assertEqual({d['target']['role'] for d in run['drafts']}, {'venues', 'sponsors', 'catering', 'contacts'})
        draft = run['drafts'][0]
        service.edit(run['id'], draft['id'], {'subject': 'Revised ask', 'body': 'Please donate supplies.'})
        restored = self.service()
        saved = restored.history(self.event['id'])[0]['drafts'][0]
        self.assertEqual(saved['body'], 'Please donate supplies.')
        self.assertTrue(saved['edited'])
        self.assertEqual(restored.history('another-event'), [])

    def test_followup_receives_saved_drafts(self):
        service = self.service()
        service.start(self.event, 'First request', self.targets)
        first = self.wait(service)
        service.edit(first['id'], first['drafts'][0]['id'], {'subject':'My subject', 'body':'My edit'})
        seen = []
        def generate(prompt, event, targets, history, config):
            seen.extend(history)
            return parse_drafts(json.dumps(result_for(targets)), targets)
        service.generator = generate
        service.start(self.event, 'Make it shorter', self.targets)
        self.wait(service)
        self.assertEqual(seen[0]['drafts'][0]['body'], 'My edit')

    def test_busy_failure_and_retry(self):
        release = threading.Event()
        self.addCleanup(release.set)
        def fail(*args):
            release.wait(2)
            raise RuntimeError('secret-provider-token')
        service = self.service(fail)
        service.start(self.event, 'Start', self.targets)
        with self.assertRaises(ChatBusy):
            service.start(self.event, 'Duplicate', self.targets)
        release.set()
        run = self.wait(service)
        self.assertEqual(run['status'], 'failed')
        self.assertNotIn('secret-provider-token', json.dumps(run))
        service.generator = lambda *args: parse_drafts(json.dumps(result_for(self.targets)), self.targets)
        service.start(self.event, 'Retry', self.targets)
        self.assertEqual(self.wait(service)['status'], 'completed')

    def test_missing_config_does_not_create_run(self):
        def missing():
            raise ChatUnavailable('Configure credentials')
        service = self.service(configure=missing)
        with self.assertRaises(ChatUnavailable):
            service.start(self.event, 'Start', self.targets)
        self.assertEqual(service.history(self.event['id']), [])
        for prompt in ('', '  ', None, 'x' * 5001):
            with self.assertRaises(ValueError):
                service.start(self.event, prompt, self.targets)

    def test_restart_marks_interrupted(self):
        service = self.service()
        with service.connect() as db:
            service.write(db, dict(id='interrupted', event_id=self.event['id'], status='running', drafts=[]))
        self.assertEqual(self.service().history(self.event['id'])[0]['status'], 'failed')

    def test_output_contract_and_recipient_routing(self):
        targets = targets_for(dict(id='new'), self.workspace, {'venues':['Imported venue']})
        self.assertEqual(targets[0]['name'], 'Imported venue')
        self.assertFalse(targets[0]['is_mock'])
        self.assertTrue(targets[1]['unassigned'])
        valid = result_for(targets)
        reply, drafts = parse_drafts('```json\n' + json.dumps(valid) + '\n```', targets)
        self.assertEqual(drafts[0]['target'], targets[0])
        for field, value in [('target_id', 'unknown'), ('body', ''), ('subject', ['invalid'])]:
            bad = result_for(targets)
            bad['drafts'][0][field] = value
            with self.assertRaises(ValueError):
                parse_drafts(json.dumps(bad), targets)
        bad = result_for(targets)
        bad['drafts'][1]['target_id'] = targets[0]['id']
        with self.assertRaises(ValueError):
            parse_drafts(json.dumps(bad), targets)
        with self.assertRaises(ValueError):
            targets_for(self.event, self.workspace, {'venues':['x'] * 4})

    def test_http_chat_and_edit(self):
        service = self.service()
        class TestHandler(Handler):
            database = self.database
            chat = service
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(TestHandler, directory=str(Path(__file__).resolve().parents[1] / 'operator_app/static')))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        def post(path, value, origin=None):
            headers = {'Content-Type':'application/json'}
            if origin:
                headers['Origin'] = origin
            return urlopen(Request(base + path, json.dumps(value).encode(), headers), timeout=3)
        with post('/api/chat', {'event_id':self.event['id'], 'prompt':'Plan a repair day'}) as response:
            self.assertEqual(response.status, 202)
        run = self.wait(service)
        draft = run['drafts'][0]
        with post('/api/message-drafts', dict(run_id=run['id'], draft_id=draft['id'], subject='Hello', body='Updated')) as response:
            self.assertEqual(json.load(response)['body'], 'Updated')
        with urlopen(base + '/api/chat?event_id=' + self.event['id']) as response:
            self.assertEqual(json.load(response)['runs'][0]['drafts'][0]['body'], 'Updated')
        with self.assertRaises(HTTPError) as error:
            post('/api/chat', {'event_id':self.event['id'], 'prompt':'Start'}, 'https://example.com')
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error:
            post('/api/chat', {'event_id':'missing', 'prompt':'Start'})
        self.assertEqual(error.exception.code, 400)
        with urlopen(base + '/chat.js') as response:
            self.assertEqual(response.status, 200)


if __name__ == '__main__':
    unittest.main()
