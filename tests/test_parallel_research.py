"""Verify five-way orchestration, partial results, evidence labels and cleanup."""
import json
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent_runtime.research import (ROLES, ResearchBrief, parse_findings, research_event,
                                    validate_credentials, worker_prompt)
from agent_runtime.runtime import AgentResult, DaytonaOpenCodeRuntime, RuntimeConfig, web_activity
from test_agent_runtime import client_fixture, sdk_module


def brief_fixture():
    path = Path(__file__).resolve().parents[1] / 'examples/event-research.json'
    return ResearchBrief.from_dict(json.loads(path.read_text()))


def findings(role):
    return {'summary': f'{role} research', 'candidates': [{
        'name': f'{role} option', 'rationale': 'Fits the event',
        'source_urls': [f'https://example.org/{role}'], 'details': {'cost_usd': None}}],
        'open_questions': ['Confirm availability and pricing.']}


class RuntimeFactory:
    """A barrier proves all five isolated workers enter their runs concurrently."""
    def __init__(self, fail=None, cleanup_fail=None, malformed=None, no_web=False):
        self.barrier = threading.Barrier(5, timeout=10)
        self.lock = threading.Lock()
        self.instances = []
        self.fail = fail
        self.cleanup_fail = cleanup_fail
        self.malformed = malformed
        self.no_web = no_web

    def __call__(self, config, *, env):
        owner = self

        class Runtime:
            def __init__(self):
                with owner.lock:
                    self.sandbox_id = 'sandbox-' + str(len(owner.instances))
                    owner.instances.append(self)
                self.sandbox = SimpleNamespace(id=self.sandbox_id)
                self.config = config
                self.role = None
                self.cleanup_called = False

            def __enter__(self):
                return self

            def run(self, prompt):
                self.role = next(role for role in ROLES if f'You are the {role} researcher' in prompt)
                owner.barrier.wait()
                if self.document_store:
                    self.document_store.ingest_events(self.role)
                if self.role == owner.fail:
                    raise RuntimeError('private-provider-secret')
                return AgentResult(self.sandbox_id, 'session-' + self.role,
                                   'invalid JSON' if self.role == owner.malformed else json.dumps(findings(self.role)),
                                   3, 'off', document_keys=('shared-document', self.role + '-document'),
                                   web_search_count=0 if owner.no_web else 1,
                                   fetched_urls=() if owner.no_web else (f'https://example.org/{self.role}',))

            def __exit__(self, *args):
                self.cleanup_called = True
                if self.role == owner.cleanup_fail:
                    raise RuntimeError('private-cleanup-secret')
                self.sandbox = None

        return Runtime()


class ParallelResearchTests(unittest.TestCase):
    def test_exactly_five_concurrent_isolated_workers(self):
        factory = RuntimeFactory()
        report = research_event(brief_fixture(), RuntimeConfig('openai/example'), env={}, runtime_factory=factory)
        self.assertEqual(report.status, 'completed')
        self.assertEqual([worker.role for worker in report.workers], list(ROLES))
        self.assertEqual(len({worker.sandbox_id for worker in report.workers}), 5)
        self.assertEqual(set(report.findings), set(ROLES))
        self.assertEqual(report.document_keys.count('shared-document'), 1)
        self.assertTrue(all(instance.cleanup_called and instance.sandbox is None for instance in factory.instances))
        self.assertTrue(all(instance.config.enable_websearch for instance in factory.instances))
        self.assertTrue(all(worker.cleanup == 'delete_requested' for worker in report.workers))
        self.assertEqual(report.findings['venues'][0]['evidence_status'], 'source_retrieved')
        self.assertEqual(report.findings['venues'][0]['status'], 'proposed')

    def test_one_failure_preserves_other_results_and_cleans_every_worker(self):
        factory = RuntimeFactory(fail='catering')
        report = research_event(brief_fixture(), RuntimeConfig('openai/example'), env={}, runtime_factory=factory)
        self.assertEqual(report.status, 'partial')
        self.assertEqual(sum(worker.status == 'completed' for worker in report.workers), 4)
        self.assertEqual(report.findings['catering'], [])
        self.assertTrue(all(instance.cleanup_called for instance in factory.instances))
        self.assertNotIn('private-provider-secret', str(report))

    def test_cleanup_failure_is_visible_without_losing_completed_output(self):
        factory = RuntimeFactory(cleanup_fail='venues')
        report = research_event(brief_fixture(), RuntimeConfig('openai/example'), env={}, runtime_factory=factory)
        worker = next(worker for worker in report.workers if worker.role == 'venues')
        self.assertEqual(report.status, 'partial')
        self.assertEqual(worker.cleanup, 'failed')
        self.assertIsNotNone(worker.sandbox_id)
        self.assertIsNotNone(worker.agent)
        self.assertTrue(report.findings['venues'])
        self.assertNotIn('private-cleanup-secret', str(report))

    def test_invalid_output_and_unobserved_search_are_not_success(self):
        for factory in (RuntimeFactory(malformed='contacts'), RuntimeFactory(no_web=True)):
            report = research_event(brief_fixture(), RuntimeConfig('openai/example'), env={}, runtime_factory=factory)
            self.assertNotEqual(report.status, 'completed')
            self.assertTrue(all(instance.cleanup_called for instance in factory.instances))
            if factory.no_web:
                self.assertTrue(all(worker.status == 'incomplete' for worker in report.workers))
                self.assertEqual(report.findings['contacts'][0]['evidence_status'], 'unverified')

    def test_contract_rejects_unsafe_urls_and_excess_candidates(self):
        agent = AgentResult('sandbox', 'session', '', 1, 'off')
        value = findings('contacts')
        value['candidates'][0]['source_urls'] = ['https://user:secret@example.org/']
        with self.assertRaises(ValueError):
            parse_findings(json.dumps(value), limit=5, agent=agent)
        with self.assertRaises(ValueError):
            parse_findings(json.dumps(findings('contacts')), limit=0, agent=agent)

    def test_preflight_and_brief_fail_before_provisioning(self):
        with patch('agent_runtime.research.DaytonaOpenCodeRuntime') as runtime:
            with self.assertRaisesRegex(ValueError, 'DAYTONA_API_KEY'):
                research_event(brief_fixture(), RuntimeConfig('openai/example'), env={})
        runtime.assert_not_called()
        with self.assertRaises(ValueError):
            validate_credentials(RuntimeConfig('openai/example'), {'DAYTONA_API_KEY': 'key'})
        with self.assertRaises(ValueError):
            replace(brief_fixture(), event=replace(brief_fixture().event, organization_id='another'))
        for role in ROLES:
            self.assertIn('websearch', worker_prompt(role, brief_fixture()))

    def test_runtime_enables_discovery_and_counts_only_completed_tools(self):
        import sys
        client = client_fixture()
        with patch.dict(sys.modules, {'daytona': sdk_module()}):
            with DaytonaOpenCodeRuntime(RuntimeConfig('openai/example', enable_websearch=True),
                                       client=client, env={'OPENAI_API_KEY': 'model-key',
                                                           'SPECTRON_API_KEY': '', 'DAYTONA_API_KEY': 'host-key'}):
                pass
        params = client.create.call_args.args[0]
        self.assertEqual(params['env_vars'], {'OPENAI_API_KEY': 'model-key', 'OPENCODE_ENABLE_EXA': '1'})
        events = '\n'.join(json.dumps({'type': 'tool_use', 'part': {'tool': tool, 'state': {
            'status': status, 'input': {'url': 'https://example.org/'}}}})
            for tool, status in [('websearch', 'completed'), ('webfetch', 'completed'), ('websearch', 'error')])
        self.assertEqual(web_activity(events + '\n[]\n{}\nnot json'), (1, ('https://example.org/',)))

    def test_workers_share_one_host_document_adapter(self):
        active = 0
        peak = 0

        def ingest(_):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            time.sleep(0.01)
            active -= 1

        adapter = MagicMock()
        adapter.ingest_events.side_effect = ingest
        with patch('document_store.DocumentStore', return_value=adapter) as store:
            factory = RuntimeFactory()
            research_event(brief_fixture(), RuntimeConfig('openai/example'),
                           env={'SPECTRON_URL': 'https://memory.example.org'}, runtime_factory=factory)
        store.assert_called_once()
        self.assertEqual(len({id(instance.document_store) for instance in factory.instances}), 1)
        self.assertEqual(adapter.ingest_events.call_count, 5)
        self.assertEqual(peak, 1)

    def test_real_runtime_boot_failure_still_requests_cleanup(self):
        import sys
        clients = []
        lock = threading.Lock()

        def factory(config, *, env):
            client = client_fixture()
            with lock:
                index = len(clients)
                clients.append(client)
            client.create.return_value.id = f'real-lifecycle-{index}'

            def execute(command, **kwargs):
                if index == 0 and command.startswith('npm install'):
                    return SimpleNamespace(exit_code=1, result='')
                if command.startswith('python3 /home/daytona/runtime/runner.py'):
                    request = next(json.loads(call.args[0]) for call in reversed(
                        client.create.return_value.fs.upload_file.call_args_list)
                        if call.args[1].endswith('/request.json'))
                    role = next(role for role in ROLES if f'You are the {role} researcher' in request['prompt'])
                    events = [{'type': 'tool_use', 'part': {'tool': tool, 'state': {
                        'status': 'completed', 'input': {'url': f'https://example.org/{role}'}}}}
                        for tool in ('websearch', 'webfetch')]
                    events.append({'type': 'text', 'sessionID': str(index),
                                   'part': {'text': json.dumps(findings(role))}})
                    return SimpleNamespace(exit_code=0, result='\n'.join(json.dumps(event) for event in events))
                return SimpleNamespace(exit_code=0, result='')

            client.create.return_value.process.exec.side_effect = execute
            return DaytonaOpenCodeRuntime(config, env=env, client=client)

        with patch.dict(sys.modules, {'daytona': sdk_module()}):
            report = research_event(brief_fixture(), RuntimeConfig('openai/example'), env={}, runtime_factory=factory)
        self.assertEqual(report.status, 'partial')
        self.assertEqual(sum(worker.status == 'completed' for worker in report.workers), 4)
        self.assertTrue(all(worker.cleanup == 'delete_requested' for worker in report.workers))
        self.assertTrue(all(worker.sandbox_id is not None for worker in report.workers))
        for client in clients:
            client.delete.assert_called_once_with(client.create.return_value)


if __name__ == '__main__':
    unittest.main()
