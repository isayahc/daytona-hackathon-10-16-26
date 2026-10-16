"""Runtime lifecycle and credential boundary tests without cloud execution."""
from __future__ import annotations
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from agent_runtime.runtime import DaytonaOpenCodeRuntime, RuntimeConfig, parse_events, tracing_settings


def sdk_module() -> SimpleNamespace:
    """Provide a lightweight SDK seam so ordinary tests need no optional dependency."""
    return SimpleNamespace(CreateSandboxFromSnapshotParams=lambda **kwargs: kwargs, Daytona=MagicMock())


def client_fixture() -> MagicMock:
    """Create a Daytona client that returns a sandbox with successful commands."""
    client = MagicMock()
    client.create.return_value.id = 'sandbox-test'
    client.create.return_value.process.exec.return_value = SimpleNamespace(exit_code=0, result='')
    return client


class RuntimeTests(unittest.TestCase):
    """Verify context cleanup, session continuation, and backend configuration."""

    def test_configuration_validation(self) -> None:
        """Reject incomplete model identifiers and invalid timeout settings."""
        for config in [dict(model='missing-provider'), dict(model='a/b', tracing='invalid'),
                       dict(model='a/b', turn_timeout=0)]:
            with self.assertRaises(ValueError):
                RuntimeConfig(**config)

    def test_tracing_credentials_are_backend_specific(self) -> None:
        """Never silently choose a tracing backend or transfer unrelated keys."""
        with self.assertRaises(ValueError):
            tracing_settings('arize', {'ARIZE_API_KEY': 'key'})
        config = tracing_settings('arize', {'ARIZE_API_KEY': 'key', 'ARIZE_SPACE_ID': 'space',
                                            'PHOENIX_API_KEY': 'other'})
        self.assertNotIn('PHOENIX_API_KEY', config)
        self.assertEqual(config['ARIZE_LOG_PROMPTS'], 'false')
        self.assertEqual(tracing_settings('off', {'ARIZE_API_KEY': 'key'}), {})

    def test_parse_opencode_events(self) -> None:
        """Handle JSONL output without mistaking empty/error output for success."""
        output = '\n'.join(['startup text', json.dumps({'type': 'text', 'sessionID': 'ses_one',
                                                       'part': {'text': 'A plan'}})])
        self.assertEqual(parse_events(output), ('ses_one', 'A plan', 1))
        for bad in ['', '{}', '{"type":"error"}']:
            with self.assertRaises(RuntimeError):
                parse_events(bad)

    def test_private_environment_and_cleanup(self) -> None:
        """Provider credentials cross the sandbox boundary; outreach/session keys do not."""
        client = client_fixture()
        env = {'OPENAI_API_KEY': 'model-secret', 'ANCHOR_API_KEY': 'browser-secret',
               'SURREAL_PASS': 'db-secret', 'DAYTONA_API_KEY': 'host-secret'}
        with patch.dict(sys.modules, {'daytona': sdk_module()}):
            with DaytonaOpenCodeRuntime(RuntimeConfig('openai/example'), client=client, env=env):
                pass
        params = client.create.call_args.args[0]
        self.assertFalse(params['public'])
        self.assertEqual(params['env_vars'], {'OPENAI_API_KEY': 'model-secret'})
        client.delete.assert_called_once_with(client.create.return_value)

    def test_cleanup_on_failed_bootstrap(self) -> None:
        """A package-install failure must release the already-created sandbox."""
        client = client_fixture()
        client.create.return_value.process.exec.return_value.exit_code = 1
        with patch.dict(sys.modules, {'daytona': sdk_module()}):
            with self.assertRaises(RuntimeError):
                with DaytonaOpenCodeRuntime(RuntimeConfig('openai/example'), client=client, env={}):
                    pass
        client.delete.assert_called_once()

    def test_multi_turn_session_and_safe_prompt_transport(self) -> None:
        """Carry the returned session ID and keep user prompts out of shell commands."""
        client = client_fixture()
        sandbox = client.create.return_value
        output = json.dumps({'type': 'text', 'sessionID': 'ses_one', 'part': {'text': 'Done'}})
        with patch.dict(sys.modules, {'daytona': sdk_module()}):
            with DaytonaOpenCodeRuntime(RuntimeConfig('openai/example'), client=client, env={}) as runtime:
                sandbox.process.exec.return_value.result = output
                runtime.run('First turn')
                runtime.run('Second turn; $(do not execute)')
        requests = [json.loads(call.args[0]) for call in sandbox.fs.upload_file.call_args_list
                    if call.args[1].endswith('/request.json')]
        self.assertIsNone(requests[0]['session_id'])
        self.assertEqual(requests[1]['session_id'], 'ses_one')
        self.assertIn('$(do not execute)', requests[1]['prompt'])
        self.assertTrue(all('$(do not execute)' not in call.args[0] for call in sandbox.process.exec.call_args_list))

    def test_cleanup_after_turn_failure(self) -> None:
        """Structured agent errors propagate and trigger sandbox cleanup."""
        client = client_fixture()
        with patch.dict(sys.modules, {'daytona': sdk_module()}):
            with self.assertRaises(RuntimeError):
                with DaytonaOpenCodeRuntime(RuntimeConfig('openai/example'), client=client, env={}) as runtime:
                    client.create.return_value.process.exec.return_value.result = '{"type":"error"}'
                    runtime.run('Test')
        client.delete.assert_called_once()

    def test_arize_bootstrap_does_not_put_keys_in_commands(self) -> None:
        """Use the explicit private installer file and pin the downloaded tracing revision."""
        client = client_fixture()
        with patch.dict(sys.modules, {'daytona': sdk_module()}):
            with DaytonaOpenCodeRuntime(RuntimeConfig('openai/example', tracing='arize'), client=client,
                                       env={'ARIZE_API_KEY': 'secret-test-key', 'ARIZE_SPACE_ID': 'space'}):
                pass
        commands = [call.args[0] for call in client.create.return_value.process.exec.call_args_list]
        self.assertTrue(any('--non-interactive' in command for command in commands))
        self.assertTrue(all('secret-test-key' not in command for command in commands))


if __name__ == '__main__':
    unittest.main()
