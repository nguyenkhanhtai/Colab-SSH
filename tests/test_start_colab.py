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

import start_colab as app


class SessionTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_urls(self):
        self.assertEqual(app.github_url('https://github.com/a/repo.git'),
                         ('https://github.com/a/repo.git', 'repo'))
        for value in ['https://token@github.com/a/b', 'https://example.com/a/b',
                      'https://github.com/a/..', 'https://github.com/a/b/tree/main']:
            with self.assertRaises(argparse.ArgumentTypeError):
                app.github_url(value)

    @patch('start_colab.shutil.which', return_value='/bin/colab')
    @patch('start_colab.subprocess.run')
    def test_sequence_and_failure(self, run, which):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(['https://github.com/a/b', '--session', 'test']), 0)
        self.assertEqual([c.args[0][1] for c in run.call_args_list],
                         ['new', 'exec', 'drivemount', 'exec'])
        self.assertEqual(run.call_args_list[2].args[0][-1], '/content/b/drive')
        run.reset_mock()
        run.side_effect = [None, subprocess.CalledProcessError(1, 'clone')]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(app.main(['https://github.com/a/b']), 1)
        self.assertEqual(run.call_count, 2)

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

    @patch('start_colab.getpass.getpass', return_value='test-secret')
    @patch('start_colab.shutil.which', return_value='/bin/colab')
    @patch('start_colab.subprocess.run')
    def test_pat_uses_ssh_stdin_only(self, run, which, prompt):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(app.main(['https://github.com/a/b', '--pat']), 0)
        clone = run.call_args_list[1]
        self.assertEqual(clone.args[0][0], 'ssh')
        self.assertEqual(json.loads(clone.kwargs['input']), 'test-secret')
        self.assertNotIn('test-secret', str(clone.args))
        self.assertNotIn('test-secret', output.getvalue())
        self.assertIn('credential.helper=', clone.args[0][-1])

    @patch('start_colab.shutil.which', return_value='/bin/colab')
    @patch('start_colab.subprocess.run')
    def test_environment_token(self, run, which):
        with patch.dict(os.environ, {'GH_TOKEN': 'env-secret'}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(['https://github.com/a/b']), 0)
        self.assertEqual(json.loads(run.call_args_list[1].kwargs['input']), 'env-secret')

    @patch('start_colab.getpass.getpass', return_value='')
    @patch('start_colab.shutil.which', return_value='/bin/colab')
    @patch('start_colab.subprocess.run')
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
