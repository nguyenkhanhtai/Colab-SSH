import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import colab_session.server.app as colab_server


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
        self.assertIn('id="treeDialog"', colab_server.get_dashboard_html())
        self.assertIn('Files 📁', colab_server.get_dashboard_html())
        self.assertIn('openTreeModal', colab_server.get_dashboard_html())
        self.assertIn('id="metricsDialog"', colab_server.get_dashboard_html())
        self.assertIn('Metrics 📊', colab_server.get_dashboard_html())
        self.assertIn('openMetricsModal', colab_server.get_dashboard_html())
        self.assertNotIn('<form id="compute"', colab_server.get_dashboard_html())
        self.assertNotIn('id="jobDialog"', colab_server.HTML)
        self.assertNotIn('openJobModal', colab_server.HTML)
        self.assertNotIn('Open notebook', colab_server.HTML)


class ServerAppTests(unittest.TestCase):
    def test_repository_pat_travels_over_stdin(self):
        with tempfile.TemporaryDirectory() as tmp, patch('colab_session.server.app.session_manager.active_names', return_value=set()), \
                patch('colab_session.server.app.subprocess.Popen', return_value=FakeProcess()) as popen:
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
        with tempfile.TemporaryDirectory() as tmp, patch('colab_session.server.app.session_manager.active_names', return_value=set()), \
                patch('colab_session.server.app.session_manager.sessions', return_value=[]), \
                patch('colab_session.server.app.subprocess.Popen', return_value=process):
            app = colab_server.App('/bin/colab')
            app.logs = Path(tmp)
            app.create({'session': 'deleted-job', 'gpu': 'T4'})
            self.assertEqual(app.dashboard_sessions(), [])
            self.assertNotIn('deleted-job', app.jobs)

    def test_stop_terminates_provisioning_and_removes_job(self):
        process = FakeProcess()
        with tempfile.TemporaryDirectory() as tmp, patch('colab_session.server.app.session_manager.active_names', return_value=set()), \
                patch('colab_session.server.app.session_manager.stop') as stop, \
                patch('colab_session.server.app.subprocess.Popen', return_value=process):
            app = colab_server.App('/bin/colab')
            app.logs = Path(tmp)
            app.create({'session': 'running-job', 'gpu': 'T4'})
            app.stop('running-job')
        self.assertTrue(process.terminated)
        self.assertNotIn('running-job', app.jobs)
        stop.assert_called_once_with('/bin/colab', 'running-job')

    def test_job_status_reports_provisioning_stage_and_progress(self):
        process = FakeProcess()
        with tempfile.TemporaryDirectory() as tmp, patch('colab_session.server.app.session_manager.active_names', return_value=set()), \
                patch('colab_session.server.app.subprocess.Popen', return_value=process):
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
        with tempfile.TemporaryDirectory() as tmp, patch('colab_session.server.app.session_manager.active_names', return_value=set()), \
                patch('colab_session.server.app.subprocess.Popen', return_value=FakeProcess()):
            app = colab_server.App('/bin/colab')
            app.logs = Path(tmp)
            log = Path(tmp) / 'same-name.log'
            log.write_text('READY: stale run')
            app.create({'session': 'same-name', 'gpu': 'T4'})
            self.assertEqual(log.read_text(), '')

    def test_drive_authorization_can_resume_provisioning(self):
        process = FakeProcess()
        with tempfile.TemporaryDirectory() as tmp, patch('colab_session.server.app.session_manager.active_names', return_value=set()), \
                patch('colab_session.server.app.subprocess.Popen', return_value=process):
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
        with tempfile.TemporaryDirectory() as tmp, patch('colab_session.server.app.session_manager.active_names', return_value=set()), \
                patch('colab_session.server.app.subprocess.Popen', return_value=FakeProcess()) as popen:
            app = colab_server.App('/bin/colab')
            app.logs = Path(tmp)
            app.create({'session': 'scratch', 'gpu': 'T4', 'repository': {'enabled': False}})
        command = popen.call_args.args[0]
        self.assertNotIn('--pat-stdin', command)
        self.assertIn('--skip-drive', command)
        self.assertNotIn('github.com', ' '.join(command))

    def test_create_with_restore_key(self):
        with tempfile.TemporaryDirectory() as tmp, patch('colab_session.server.app.session_manager.active_names', return_value=set()), \
                patch('colab_session.server.app.subprocess.Popen', return_value=FakeProcess()) as popen:
            app = colab_server.App('/bin/colab')
            app.logs = Path(tmp)
            app.create({'session': 'restored', 'gpu': 'T4', 'restore_key': 'bk-1234abcd'})
        command = popen.call_args.args[0]
        self.assertIn('--restore', command)
        self.assertIn('bk-1234abcd', command)
        self.assertNotIn('--skip-drive', command)

    def test_create_with_restore_key_and_repo_fails(self):
        with tempfile.TemporaryDirectory() as tmp, patch('colab_session.server.app.session_manager.active_names', return_value=set()):
            app = colab_server.App('/bin/colab')
            app.logs = Path(tmp)
            with self.assertRaises(ValueError):
                app.create({'session': 'invalid', 'gpu': 'T4', 'restore_key': 'bk-1234abcd',
                            'repository': {'enabled': True, 'url': 'https://github.com/a/b'}})

    def test_backup_endpoint(self):
        app = colab_server.App('/bin/colab')
        with patch('colab_session.server.app.backup_manager.backup', return_value={'key': 'bk-1234abcd', 'size_mb': 12.3, 'path': '/p'}) as mock_backup, \
                patch('colab_session.server.app.session_manager.validate_name'):
            res = app.backup('session-1')
        self.assertEqual(res['key'], 'bk-1234abcd')
        mock_backup.assert_called_once_with('/bin/colab', 'session-1')

    def test_cross_origin_request_is_blocked(self):
        app = colab_server.App('/bin/colab')
        handler_cls = colab_server.handler_for(app)
        handler = handler_cls.__new__(handler_cls)
        handler.headers = {'Origin': 'http://evil.com'}
        replied = {}
        def mock_reply(data, status=200):
            replied['data'] = data
            replied['status'] = status
        handler.reply = mock_reply
        self.assertFalse(handler.validate_origin())
        self.assertEqual(replied['status'], 403)
        self.assertIn('forbidden', replied['data']['error'])

    def test_inspect_tree_endpoint(self):
        app = colab_server.App('/bin/colab')
        mock_tree = {
            'name': 'content',
            'path': '/content',
            'is_dir': True,
            'children': [
                {'name': 'train.py', 'path': '/content/train.py', 'is_dir': False, 'size_human': '2.1 KB'}
            ],
            'total_items': 1,
            'shown_items': 1,
            'has_more': False,
        }
        with patch.object(app.job_manager, 'tree', return_value=mock_tree) as mock_m_tree, \
                patch('colab_session.server.app.session_manager.validate_name'):
            handler_cls = colab_server.handler_for(app)
            handler = handler_cls.__new__(handler_cls)
            handler.path = '/api/sessions/session-1/tree?path=/content&depth=2&limit=10'
            replied = {}
            def mock_reply(data, status=200):
                replied['data'] = data
                replied['status'] = status
            handler.reply = mock_reply
            handler.do_GET()

            self.assertEqual(replied['status'], 200)
            self.assertEqual(replied['data']['session'], 'session-1')
            self.assertEqual(replied['data']['path'], '/content')
            self.assertEqual(replied['data']['tree']['name'], 'content')
            self.assertIn('/content/', replied['data']['rendered'])
            mock_m_tree.assert_called_once_with(
                session='session-1',
                path='/content',
                max_depth=2,
                max_items=10,
                show_hidden=False,
            )

    def test_session_metrics_endpoint(self):
        app = colab_server.App('/bin/colab')
        mock_metrics = {
            'session': 'session-1',
            'gpu': {'name': 'Tesla T4', 'util_pct': 0, 'memory_used_mb': 100, 'memory_total_mb': 15360, 'temperature_c': 35},
            'cpu': {'load_1m': 0.1, 'load_5m': 0.2, 'load_15m': 0.3},
            'ram': {'used_mb': 1000, 'total_mb': 12000},
            'quota': {'total_vram_mb': 15360, 'allocated_vram_mb': 0, 'available_vram_mb': 15360, 'allocations': {}}
        }
        with patch('colab_session.metrics.collector.get_session_metrics', return_value=mock_metrics) as mock_get_metrics, \
                patch('colab_session.server.app.session_manager.validate_name'):
            handler_cls = colab_server.handler_for(app)
            handler = handler_cls.__new__(handler_cls)
            handler.path = '/api/sessions/session-1/metrics'
            replied = {}
            def mock_reply(data, status=200):
                replied['data'] = data
                replied['status'] = status
            handler.reply = mock_reply
            handler.do_GET()

            self.assertEqual(replied['status'], 200)
            self.assertEqual(replied['data']['session'], 'session-1')
            self.assertEqual(replied['data']['gpu']['name'], 'Tesla T4')
            mock_get_metrics.assert_called_once_with('/bin/colab', 'session-1')

    def test_run_job_passes_vram_and_timeout(self):
        app = colab_server.App('/bin/colab')
        with patch.object(app.job_manager, 'run') as mock_run, \
                patch('colab_session.server.app.session_manager.validate_name'):
            from colab_session.jobs.models import Job, JobStatus
            mock_job = Job(id="job-1", command="python3 test.py", session="session-1", cwd="/content", status=JobStatus.RUNNING)
            mock_run.return_value = mock_job

            handler_cls = colab_server.handler_for(app)
            handler = handler_cls.__new__(handler_cls)
            handler.headers = {}
            handler.path = '/api/sessions/session-1/jobs'
            payload = {
                'command': 'python3 test.py',
                'detached': True,
                'vram': '8GB',
                'timeout': '1h'
            }
            handler.body = lambda: payload
            replied = {}
            def mock_reply(data, status=200):
                replied['data'] = data
                replied['status'] = status
            handler.reply = mock_reply
            handler.validate_origin = lambda: True
            handler.do_POST()

            self.assertEqual(replied['status'], 200)
            self.assertEqual(replied['data']['id'], 'job-1')
            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            self.assertEqual(kwargs['vram'], '8GB')
            self.assertEqual(kwargs['timeout'], '1h')


if __name__ == '__main__':
    unittest.main()

