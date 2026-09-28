from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import setup_ssh


class SSHConfigTests(unittest.TestCase):
    def test_sessions_keep_separate_hosts_and_keys(self):
        with tempfile.TemporaryDirectory(prefix='ssh config ') as tmp:
            root = Path(tmp)
            key = root / 'identity'
            key.touch()
            with patch.object(setup_ssh, 'ROOT', root):
                config, _ = setup_ssh.configure('colab-first', '/path with spaces/colab', key)
                setup_ssh.configure('colab-second', '/path with spaces/colab', key)
                setup_ssh.configure('colab-first', '/path with spaces/colab', key)
            text = config.read_text()
            self.assertEqual(text.count('Host colab-first\n'), 1)
            self.assertEqual(text.count('Host colab-second\n'), 1)
            self.assertIn('colab-first.known_hosts', text)
            self.assertIn('colab-second.known_hosts', text)
            self.assertIn("'/path with spaces/colab' ssh", text)
            self.assertIn('StrictHostKeyChecking accept-new', text)

    def test_install_preserves_existing_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.ssh').mkdir()
            user_config = root / '.ssh/config'
            user_config.write_text('Host existing\n    HostName example.org\n')
            with patch.object(setup_ssh.Path, 'home', return_value=root):
                setup_ssh.install(root / 'tool/config')
                setup_ssh.install(root / 'tool/config')
            text = user_config.read_text()
            self.assertEqual(text.count('Include '), 1)
            self.assertIn('Host existing\n    HostName example.org\n', text)
