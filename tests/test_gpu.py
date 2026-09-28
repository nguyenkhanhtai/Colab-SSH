import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from setup_gpu import prepare_gpu, remote_code


class GPUTests(unittest.TestCase):
    def test_library_path_loader_and_shell_setup_are_repeatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            driver = root / 'nvidia'
            driver.mkdir()
            home = root / 'home'
            home.mkdir()
            loader = root / 'ld.so.conf.d'
            result = subprocess.CompletedProcess([], 0, stdout='Tesla T4\n', stderr='')
            with patch.dict(os.environ, {'LD_LIBRARY_PATH': '/existing'}), patch('setup_gpu.os.geteuid', return_value=0), patch('setup_gpu.shutil.which', return_value='/sbin/ldconfig'), patch('setup_gpu.subprocess.run', return_value=result) as run, contextlib.redirect_stdout(io.StringIO()):
                prepare_gpu('T4', str(driver), home, loader)
                prepare_gpu('T4', str(driver), home, loader)
                self.assertEqual(os.environ['LD_LIBRARY_PATH'], str(driver) + ':/existing')
                self.assertEqual(run.call_args_list[0].args[0], ['/sbin/ldconfig'])
            self.assertEqual((loader / 'colab-nvidia.conf').read_text(), str(driver) + '\n')
            self.assertEqual((home / '.bashrc').read_text().count('export LD_LIBRARY_PATH='), 1)
            self.assertEqual((home / '.profile').read_text().count('export LD_LIBRARY_PATH='), 1)

    def test_failure_reports_driver_error_and_wrong_gpu(self):
        with patch('setup_gpu.subprocess.run', return_value=subprocess.CompletedProcess([], 12, stdout='libnvidia-ml.so missing', stderr='')):
            with self.assertRaisesRegex(RuntimeError, 'libnvidia-ml.so missing'):
                prepare_gpu('T4', '/nonexistent/driver')
        with patch('setup_gpu.subprocess.run', return_value=subprocess.CompletedProcess([], 0, stdout='NVIDIA L4', stderr='')):
            with self.assertRaisesRegex(RuntimeError, 'Expected T4'):
                prepare_gpu('T4', '/nonexistent/driver')
        compile(remote_code('T4'), '<remote gpu>', 'exec')
