import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import colab_server


class CapturingBytesIO(io.BytesIO):
    def close(self):
        pass


class FakeProcess:
    def __init__(self):
        self.stdin = CapturingBytesIO()
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15


class DashboardTests(unittest.TestCase):
    def test_create_form_is_hidden_in_dashboard_dialog(self):
        self.assertIn('id="createDialog"', colab_server.HTML)
        self.assertIn('+ New session', colab_server.HTML)
        self.assertIn('id="createForm"', colab_server.HTML)
        self.assertIn('id="activeCount"', colab_server.HTML)
        self.assertIn('id="driveDialog"', colab_server.HTML)
        self.assertIn('I’ve granted access', colab_server.HTML)
        self.assertIn('class=\"progress\"', colab_server.HTML)
        self.assertIn('${E(s.stage)}', colab_server.HTML)
        self.assertIn('.auth-link.hidden{display:none}', colab_server.HTML)
        self.assertIn("Preparing session: '+x.stage+' · '+x.progress+'%'", colab_server.HTML)
        self.assertNotIn('<form id="compute"', colab_server.HTML)


class ServerAppTests(unittest.TestCase):
    def test_repository_pat_travels_over_stdin(self):
        with tempfile.TemporaryDirectory() as tmp, patch('colab_server.session_manager.active_names', return_value=set()), \
                patch('colab_server.subprocess.Popen', return_value=FakeProcess()) as popen:
            app = colab_server.App('/bin/colab')
            app.logs = Path(tmp)
            name = app.create({'session': 'alpha', 'gpu': 'L4', 'repository': {
                'enabled': True, 'url': 'https://github.com/a/private',
                'branch': 'main', 'credential': 'pat', 'pat': 'web-secret'}})
        self.assertEqual(name, 'alpha')
        command = popen.call_args.args[0]
        self.assertIn('--pat-stdin', command)
        self.assertIn('--branch', command)
        self.assertNotIn('web-secret', command)
        self.assertEqual(popen.return_value.stdin.getvalue(), b'web-secret\n')

    def test_finished_job_missing_from_colab_is_pruned(self):
        process = FakeProcess()
        process.returncode = 0
        with tempfile.TemporaryDirectory() as tmp, patch('colab_server.session_manager.active_names', return_value=set()), \
                patch('colab_server.session_manager.sessions', return_value=[]), \
                patch('colab_server.subprocess.Popen', return_value=process):
            app = colab_server.App('/bin/colab')
            app.logs = Path(tmp)
            app.create({'session': 'deleted-job', 'gpu': 'T4'})
            self.assertEqual(app.dashboard_sessions(), [])
            self.assertNotIn('deleted-job', app.jobs)

    def test_stop_terminates_provisioning_and_removes_job(self):
        process = FakeProcess()
        with tempfile.TemporaryDirectory() as tmp, patch('colab_server.session_manager.active_names', return_value=set()), \
                patch('colab_server.session_manager.stop') as stop, \
                patch('colab_server.subprocess.Popen', return_value=process):
            app = colab_server.App('/bin/colab')
            app.logs = Path(tmp)
            app.create({'session': 'running-job', 'gpu': 'T4'})
            app.stop('running-job')
        self.assertTrue(process.terminated)
        self.assertNotIn('running-job', app.jobs)
        stop.assert_called_once_with('/bin/colab', 'running-job')

    def test_job_status_reports_provisioning_stage_and_progress(self):
        process = FakeProcess()
        with tempfile.TemporaryDirectory() as tmp, patch('colab_server.session_manager.active_names', return_value=set()), \
                patch('colab_server.subprocess.Popen', return_value=process):
            app = colab_server.App('/bin/colab')
            app.logs = Path(tmp)
            app.create({'session': 'progress-job', 'gpu': 'L4'})
            log = Path(tmp) / 'progress-job.log'
            log.write_text('Session READY.\nSSH: command\nConfiguring workspace and GPU...\n')
            status = app.job_status('progress-job')
            self.assertEqual(status['status'], 'provisioning')
            self.assertEqual(status['stage'], 'Configuring workspace and GPU')
            self.assertEqual(status['progress'], 32)
            log.write_text(log.read_text() + 'Environment ready.\nDevelopment tools ready. Syncing agent context...\n')
            status = app.job_status('progress-job')
            self.assertEqual(status['stage'], 'Syncing agent context')
            self.assertEqual(status['progress'], 78)
            log.write_text(log.read_text() + 'READY: /content\n')
            process.returncode = 0
            status = app.job_status('progress-job')
            self.assertEqual(status['status'], 'ready')
            self.assertEqual(status['progress'], 100)

    def test_new_job_truncates_log_from_reused_name(self):
        with tempfile.TemporaryDirectory() as tmp, patch('colab_server.session_manager.active_names', return_value=set()), \
                patch('colab_server.subprocess.Popen', return_value=FakeProcess()):
            app = colab_server.App('/bin/colab')
            app.logs = Path(tmp)
            log = Path(tmp) / 'same-name.log'
            log.write_text('READY: stale run')
            app.create({'session': 'same-name', 'gpu': 'T4'})
            self.assertEqual(log.read_text(), '')

    def test_drive_authorization_can_resume_provisioning(self):
        process = FakeProcess()
        with tempfile.TemporaryDirectory() as tmp, patch('colab_server.session_manager.active_names', return_value=set()), \
                patch('colab_server.subprocess.Popen', return_value=process):
            app = colab_server.App('/bin/colab')
            app.logs = Path(tmp)
            app.create({'session': 'drive-job', 'gpu': 'T4', 'mount_drive': True})
            (Path(tmp) / 'drive-job.log').write_text(
                'Please visit:\nhttps://accounts.google.com/o/oauth2/v2/auth?state=test\n')
            status = app.job_status('drive-job')
            self.assertTrue(status['awaiting_drive_authorization'])
            self.assertEqual(status['authorization_url'],
                             'https://accounts.google.com/o/oauth2/v2/auth?state=test')
            app.confirm_drive('drive-job')
            self.assertEqual(process.stdin.getvalue(), b'\n')
            self.assertFalse(app.job_status('drive-job')['awaiting_drive_authorization'])

    def test_empty_workspace_has_no_repository_arguments(self):
        with tempfile.TemporaryDirectory() as tmp, patch('colab_server.session_manager.active_names', return_value=set()), \
                patch('colab_server.subprocess.Popen', return_value=FakeProcess()) as popen:
            app = colab_server.App('/bin/colab')
            app.logs = Path(tmp)
            app.create({'session': 'scratch', 'gpu': 'T4', 'repository': {'enabled': False}})
        command = popen.call_args.args[0]
        self.assertNotIn('--pat-stdin', command)
        self.assertIn('--skip-drive', command)
        self.assertNotIn('github.com', ' '.join(command))


if __name__ == '__main__':
    unittest.main()

