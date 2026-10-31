import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import colab_session.session.manager as session_manager


class SessionManagerTests(unittest.TestCase):
    def test_sessions_redacts_colab_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'sessions.json'
            state.write_text(json.dumps({
                'alpha': {'running': True, 'accelerator': 'L4', 'machine_shape': 'Standard',
                          'token': 'secret', 'endpoint': 'private'},
                'stopped': {'running': False, 'token': 'also-secret'},
            }))
            with patch('colab_session.session.manager.reconcile_ssh'), patch('colab_session.session.manager.config_for') as config:
                config.return_value.is_file.return_value = True
                rows = session_manager.sessions(state)
        self.assertEqual([row['name'] for row in rows], ['alpha'])
        self.assertEqual(rows[0]['gpu'], 'L4')
        self.assertNotIn('token', rows[0])
        self.assertNotIn('endpoint', rows[0])

    def test_reconcile_keeps_session_during_colab_automation(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'sessions.json'
            state.write_text(json.dumps({
                'mounting': {'running': 'automation(drivemount)'},
                'finished': {'running': False},
            }))
            with patch('colab_session.session.manager.ColabCliClient.live_names', return_value=set()), \
                    patch('colab_session.session.manager.reconcile_ssh') as reconcile:
                session_manager.reconcile(state, cli='/bin/colab')
        reconcile.assert_called_once_with({'mounting'})

    def test_stop_always_removes_ssh_state(self):
        with patch('colab_session.session.manager.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'colab')), \
                patch('colab_session.session.manager.remove_ssh') as remove:
            with self.assertRaises(subprocess.CalledProcessError):
                session_manager.stop('/bin/colab', 'alpha')
        remove.assert_called_once_with('alpha')

    def test_notebook_url_uses_colab_cli(self):
        completed = subprocess.CompletedProcess([], 0, stdout='https://example.test/notebook\n')
        with patch('colab_session.session.manager.subprocess.run', return_value=completed) as run:
            url = session_manager.notebook_url('/bin/colab', 'alpha')
        self.assertEqual(url, 'https://example.test/notebook')
        run.assert_called_once_with(['/bin/colab', 'url', '-s', 'alpha'], check=True,
                                    capture_output=True, text=True)

    def test_get_account_quota_parses_cli_output(self):
        mock_output = "Current balance: 250.50 compute units\nUsage rate: 5.00/hr\nActive assignments: 2"
        completed = subprocess.CompletedProcess([], 0, stdout=mock_output)
        with patch('colab_session.session.manager.subprocess.run', return_value=completed) as run, \
                patch.dict('sys.modules', {'colab_cli.common': None}):
            q = session_manager.get_account_quota('/bin/colab')
            self.assertEqual(q['status'], 'ok')
            self.assertEqual(q['balance'], 250.5)
            self.assertEqual(q['usage_rate_hourly'], 5.0)
            self.assertEqual(q['active_assignments'], 2)
            self.assertEqual(q['hours_remaining'], 50.1)

    def test_format_account_quota_table(self):
        quota = {
            'balance': 300.0,
            'usage_rate_hourly': 10.0,
            'active_assignments': 1,
            'hours_remaining': 30.0,
            'status': 'ok'
        }
        table = session_manager.format_account_quota_table(quota)
        self.assertIn("300.00 units", table)
        self.assertIn("10.00 units/hr", table)
        self.assertIn("~30.0 hours", table)


if __name__ == '__main__':
    unittest.main()
