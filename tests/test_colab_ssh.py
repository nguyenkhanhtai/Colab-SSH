import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import colab_ssh as app


class SessionTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        default = patch('colab_ssh.DEFAULT_AUTH', Path(temp.name) / 'auth.json')
        default.start()
        self.addCleanup(default.stop)
        config = patch('colab_ssh.configure', return_value=(Path('/tmp/ssh-test-config'), 'test'))
        config.start()
        self.addCleanup(config.stop)
        install = patch('colab_ssh.install')
        self.install = install.start()
        self.addCleanup(install.stop)
        for target, value in [('load_profile', {'tools': [], 'extensions': [], 'remote_settings': {}}),
                              ('register_extensions', None), ('apply_environment', None)]:
            mock = patch('colab_ssh.' + target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def test_urls(self):
        self.assertEqual(app.github_url('https://github.com/a/repo.git'),
                         ('https://github.com/a/repo.git', 'repo'))
        for value in ['https://token@github.com/a/b', 'https://example.com/a/b',
                      'https://github.com/a/..', 'https://github.com/a/b/tree/main']:
            with self.assertRaises(argparse.ArgumentTypeError):
                app.github_url(value)

    def test_finds_colab_inside_uv_tool_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool_python = Path(tmp) / 'bin/python'
            bundled_cli = tool_python.parent / 'colab'
            bundled_cli.parent.mkdir()
            bundled_cli.touch()
            with patch('colab_ssh.shutil.which', return_value=None), \
                    patch('colab_ssh.sys.executable', str(tool_python)):
                self.assertEqual(app.find_colab_cli(), str(bundled_cli))

    @patch('colab_ssh.shutil.which', return_value='/bin/colab')
    @patch('colab_ssh.subprocess.run')
    def test_sequence_and_failure(self, run, which):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(['https://github.com/a/b', '--session', 'test']), 0)
        self.assertEqual(run.call_args_list[0].args[0][1], 'new')
        self.assertEqual(run.call_args_list[1].args[0][0], 'ssh')
        self.assertEqual(run.call_args_list[2].args[0][1], 'drivemount')
        self.assertEqual(run.call_args_list[3].args[0][0], 'ssh')
        self.assertEqual(run.call_args_list[2].args[0][-1], '/content/b/drive')
        self.install.assert_called_once_with(Path('/tmp/ssh-test-config'))
        run.reset_mock()
        run.side_effect = [None, subprocess.CalledProcessError(1, 'clone')]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(app.main(['https://github.com/a/b']), 1)
        self.assertEqual(run.call_count, 2)

    @patch('colab_ssh.shutil.which', return_value='/bin/colab')
    @patch('colab_ssh.subprocess.run')
    def test_session_without_repository(self, run, which):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(['--session', 'scratch']), 0)
        self.assertEqual(run.call_args_list[0].args[0][1], 'new')
        self.assertEqual(run.call_args_list[1].args[0][0], 'ssh')
        self.assertEqual(run.call_args_list[2].args[0][1], 'drivemount')
        self.assertEqual(run.call_args_list[3].args[0][0], 'ssh')
        self.assertEqual(run.call_args_list[2].args[0][-1], '/content/drive')
        self.assertNotIn('git', run.call_args_list[1].args[0][-1])

    @patch('colab_ssh.shutil.which', return_value='/bin/colab')
    def test_branch_requires_repository(self, which):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                app.main(['--branch', 'main'])

    def test_pat_requires_repository(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                app.main(['--pat'])

    def test_existing_drive_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / 'drive').mkdir()
            marker = repo / 'drive/important.txt'
            marker.write_text('keep')
            with patch('subprocess.run'):
                with self.assertRaisesRegex(RuntimeError, 'already exists'):
                    exec(app.clone_code('https://github.com/a/b.git', tmp, None, 'drive'), {})
            self.assertEqual(marker.read_text(), 'keep')

    @patch('colab_ssh.getpass.getpass', return_value='test-secret')
    @patch('colab_ssh.shutil.which', return_value='/bin/colab')
    @patch('colab_ssh.subprocess.run')
    def test_pat_uses_ssh_stdin_only(self, run, which, prompt):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(app.main(['https://github.com/a/b', '--pat']), 0)
        clone = run.call_args_list[1]
        self.assertEqual(clone.args[0][0], 'ssh')
        self.assertEqual(json.loads(clone.kwargs['input']), 'test-secret')
        self.assertNotIn('test-secret', str(clone.args))
        self.assertNotIn('test-secret', output.getvalue())
        self.assertEqual(app.read_auth(app.DEFAULT_AUTH, 'https://github.com/a/b'), 'test-secret')
        self.assertIn('Saved PAT mapping:', output.getvalue())
        self.assertNotIn('test-secret', app.DEFAULT_AUTH.read_text())
        self.assertIn('credential.helper=', clone.args[0][-1])

    @patch('colab_ssh.shutil.which', return_value='/bin/colab')
    @patch('colab_ssh.subprocess.run')
    def test_environment_token(self, run, which):
        with patch.dict(os.environ, {'GH_TOKEN': 'env-secret'}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(['https://github.com/a/b']), 0)
        self.assertEqual(json.loads(run.call_args_list[1].kwargs['input']), 'env-secret')

    @patch('colab_ssh.shutil.which', return_value='/bin/colab')
    @patch('colab_ssh.subprocess.run')
    def test_pat_file_overrides_environment_without_exposure(self, run, which):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'token.pat'
            file.write_text('file-secret\n')
            with patch.dict(os.environ, {'GH_TOKEN': 'env-secret'}), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(app.main(['https://github.com/a/b', '--pat-file', str(file)]), 0)
        self.assertEqual(json.loads(run.call_args_list[1].kwargs['input']), 'file-secret')
        self.assertNotIn('file-secret', str(run.call_args_list[1].args))
        self.assertNotIn('file-secret', output.getvalue())

    @patch('colab_ssh.shutil.which', return_value='/bin/colab')
    @patch('colab_ssh.subprocess.run')
    def test_bad_pat_file_does_not_create_vm(self, run, which):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            app.main(['https://github.com/a/b', '--pat-file', '/nonexistent/token.pat'])
        run.assert_not_called()

    @patch('colab_ssh.shutil.which', return_value='/bin/colab')
    @patch('colab_ssh.subprocess.run')
    def test_default_auth_config(self, run, which):
        app.DEFAULT_AUTH.parent.mkdir(exist_ok=True)
        (app.DEFAULT_AUTH.parent / 'github.pat').write_text('default-secret')
        app.DEFAULT_AUTH.write_text('{"github_pat_file": "github.pat"}')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(['https://github.com/a/b']), 0)
        self.assertEqual(json.loads(run.call_args_list[1].kwargs['input']), 'default-secret')

    @patch('colab_ssh.getpass.getpass', return_value='')
    @patch('colab_ssh.shutil.which', return_value='/bin/colab')
    @patch('colab_ssh.subprocess.run')
    def test_empty_pat_fails_before_creating_vm(self, run, which, prompt):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            app.main(['https://github.com/a/b', '--pat'])
        run.assert_not_called()

    def test_askpass_cleanup_on_clone_failure(self):
        helpers = []

        def fail_clone(command, *, check, env):
            helper = Path(env['GIT_ASKPASS'])
            helpers.append(helper)
            self.assertTrue(helper.is_file())
            self.assertNotIn('test-secret', helper.read_text())
            self.assertEqual(env['COLAB_GIT_TOKEN'], 'test-secret')
            self.assertNotIn('test-secret', str(command))
            raise subprocess.CalledProcessError(128, command)

        with patch('sys.stdin', io.StringIO(json.dumps('test-secret'))), patch('subprocess.run', side_effect=fail_clone):
            with self.assertRaises(subprocess.CalledProcessError):
                exec(app.clone_code('https://github.com/a/b.git', '/content/b', None, 'drive', True), {})
        self.assertEqual(len(helpers), 1)
        self.assertFalse(helpers[0].exists())


if __name__ == '__main__':
    unittest.main()
