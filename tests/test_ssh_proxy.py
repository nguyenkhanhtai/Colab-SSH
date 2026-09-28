import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ssh_proxy import validate


class ProxyTests(unittest.TestCase):
    def test_stopped_cpu_and_wrong_gpu_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            state = home / '.config/colab-cli/sessions.json'
            state.parent.mkdir(parents=True)
            with patch('ssh_proxy.Path.home', return_value=home):
                with self.assertRaisesRegex(ValueError, 'stopped'):
                    validate('session')
                state.write_text(json.dumps({'session': {'variant': 'DEFAULT', 'accelerator': 'NONE'}}))
                with self.assertRaisesRegex(ValueError, 'CPU'):
                    validate('session')
                state.write_text(json.dumps({'session': {'variant': 'GPU', 'accelerator': 'T4'}}))
                validate('session', 'T4')
                with self.assertRaisesRegex(ValueError, 'expected L4'):
                    validate('session', 'L4')
