"""Offline contract checks for validation, delivery uncertainty, and send claims."""
import unittest
from unittest.mock import patch
import outreach


class OutreachTests(unittest.TestCase):
    """Test consequential workflow boundaries without sending real messages."""

    def test_recipients(self) -> None:
        """Accept exact recipients and reject ambiguous or hostile addresses."""
        outreach.validate_recipient('gmail', 'person@example.com')
        outreach.validate_recipient('linkedin', 'https://www.linkedin.com/in/example/')
        for address in ['https://linkedin.com.evil.test/in/example', 'https://linkedin.com/feed/',
                        'https://linkedin.com/in/example/?other=person']:
            with self.assertRaises(ValueError):
                outreach.validate_recipient('linkedin', address)
        with self.assertRaises(ValueError):
            outreach.validate_recipient('gmail', 'a@example.com,b@example.com')

    def test_uncertain_output(self) -> None:
        """Never turn prose or missing evidence into a successful delivery."""
        for response in [{}, {'data': {'result': 'Sent!'}},
                         {'data': {'result': {'status': 'sent'}}}]:
            self.assertEqual(outreach.delivery_status(response), 'needs_review')
        self.assertEqual(outreach.delivery_status({'data': {'result': {
            'status': 'sent', 'evidence': 'Visible conversation contains exact message'}}}), 'reported_sent')

    @patch.dict('os.environ', {'SURREAL_URL': 'http://localhost:8000', 'SURREAL_TOKEN': 'test'})
    def test_claim_uses_conditional_update(self) -> None:
        """A second send must not acquire a previously claimed draft."""
        memory = outreach.Memory()
        with patch.object(memory, 'query', side_effect=[[[{'status': 'attempting'}]], [[]]]) as query:
            self.assertTrue(memory.claim('key'))
            self.assertFalse(memory.claim('key'))
            self.assertIn("WHERE status = 'draft'", query.call_args.args[0])
            self.assertEqual(query.call_args.args[1], {'id': 'key'})

    @patch.dict('os.environ', {'SURREAL_URL': 'http://localhost:8000', 'SURREAL_TOKEN': 'test'})
    @patch('outreach.request', return_value={'result': [{'status': 'ERR', 'result': 'bad'}]})
    def test_database_statement_error(self, request: object) -> None:
        """HTTP success cannot hide a database query failure."""
        with self.assertRaises(RuntimeError):
            outreach.Memory().query('invalid')

    @patch.dict('os.environ', {'ANCHOR_API_KEY': 'test'})
    @patch('outreach.request', return_value={'data': {'result': {}}})
    def test_session_is_reused(self, request: object) -> None:
        """Sending targets the signed-in session instead of a fresh browser."""
        session = '123e4567-e89b-12d3-a456-426614174000'
        outreach.Anchor().send(session, {'channel': 'gmail', 'recipient': 'p@example.com',
                                        'subject': 'Hi', 'body': 'Hello'})
        self.assertIn('sessionId=' + session, request.call_args.args[0])
        self.assertEqual(request.call_args.args[1]['url'], 'https://mail.google.com/')

    @patch('sys.argv', ['outreach.py', 'send', 'key', '--session', '123e4567-e89b-12d3-a456-426614174000'])
    @patch('builtins.input', return_value='NO')
    @patch('outreach.Anchor')
    @patch('outreach.Memory')
    def test_cancel_does_not_send(self, memory: object, anchor: object, prompt: object) -> None:
        """Review cancellation never claims the draft or submits a browser task."""
        memory.return_value.get.return_value = {'channel': 'gmail', 'recipient': 'p@example.com'}
        outreach.main()
        memory.return_value.claim.assert_not_called()
        anchor.return_value.send.assert_not_called()

    @patch('sys.argv', ['outreach.py', 'send', 'key', '--session', '123e4567-e89b-12d3-a456-426614174000'])
    @patch('builtins.input', return_value='SEND')
    @patch('outreach.Anchor')
    @patch('outreach.Memory')
    def test_timeout_requires_review(self, memory: object, anchor: object, prompt: object) -> None:
        """A send timeout is recorded as uncertain and never retried."""
        memory.return_value.get.return_value = {'channel': 'gmail', 'recipient': 'p@example.com'}
        memory.return_value.claim.return_value = True
        anchor.return_value.send.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            outreach.main()
        memory.return_value.finish.assert_called_once_with('key', 'needs_review')
        anchor.return_value.send.assert_called_once()


if __name__ == '__main__':
    unittest.main()
