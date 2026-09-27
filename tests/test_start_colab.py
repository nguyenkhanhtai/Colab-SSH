import argparse
import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import start_colab as app


class SessionTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
