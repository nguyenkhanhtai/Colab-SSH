import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import session_manager


class SessionManagerTests(unittest.TestCase):
    def test_sessions_redacts_colab_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'sessions.json'
            state.write_text(json.dumps({
                'alpha': {'running': True, 'accelerator': 'L4', 'machine_shape': 'Standard',
                          'token': 'secret', 'endpoint': 'private'},
                'stopped': {'running': False, 'token': 'also-secret'},
            }))
            with patch('session_manager.reconcile_ssh'), patch('session_manager.config_for') as config:
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
            with patch('session_manager.live_names', return_value=set()), \
                    patch('session_manager.reconcile_ssh') as reconcile:
                session_manager.reconcile(state, cli='/bin/colab')
        reconcile.assert_called_once_with({'mounting'})

    def test_stop_always_removes_ssh_state(self):
        with patch('session_manager.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'colab')), \
                patch('session_manager.remove_ssh') as remove:
            with self.assertRaises(subprocess.CalledProcessError):
                session_manager.stop('/bin/colab', 'alpha')
        remove.assert_called_once_with('alpha')

    def test_notebook_url_uses_colab_cli(self):
        completed = subprocess.CompletedProcess([], 0, stdout='https://example.test/notebook\n')
        with patch('session_manager.subprocess.run', return_value=completed) as run:
            url = session_manager.notebook_url('/bin/colab', 'alpha')
        self.assertEqual(url, 'https://example.test/notebook')
        run.assert_called_once_with(['/bin/colab', 'url', '-s', 'alpha'], check=True,
                                    capture_output=True, text=True)


if __name__ == '__main__':
    unittest.main()
