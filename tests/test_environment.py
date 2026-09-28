import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import setup_environment as env


class EnvironmentTests(unittest.TestCase):
    def test_jsonc_keeps_urls_and_string_commas(self):
        value = env.read_jsonc('{// comment\n"url":"https://x/a,}", /* note */ "a":[1,],}')
        self.assertEqual(value, {'url': 'https://x/a,}', 'a': [1]})

    def test_capture_filters_machine_settings_and_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings = home / '.config/Code/User/settings.json'
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({'editor.tabSize': 4, 'terminal.integrated.env.linux':
                                           {'GH_TOKEN': 'secret'}, 'python.defaultInterpreterPath': '/local/python'}))
            with patch.object(env.Path, 'home', return_value=home), patch.object(env, 'PROFILE', home / '.local/profile.json'):
                profile = env.capture()
            self.assertEqual(profile['remote_settings'], {'editor.tabSize': 4})
            self.assertNotIn('secret', json.dumps(profile))

    def test_extension_registration_preserves_settings_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings = home / '.config/Code/User/settings.json'
            settings.parent.mkdir(parents=True)
            original = '{// comment\n"workbench.colorTheme":"Dark", "remote.SSH.defaultExtensions":["existing.ext"],}'
            settings.write_text(original)
            with patch.object(env.Path, 'home', return_value=home):
                env.register_extensions({'extensions': ['openai.chatgpt', 'existing.ext']})
                env.register_extensions({'extensions': ['openai.chatgpt']})
            data = json.loads(settings.read_text())
            self.assertEqual(data['workbench.colorTheme'], 'Dark')
            self.assertEqual(data['remote.SSH.defaultExtensions'], ['existing.ext', 'openai.chatgpt'])
            self.assertEqual(settings.with_name('settings.colab-session.backup.jsonc').read_text(), original)

    def test_remote_program_compiles(self):
        compile(env.remote_code(), '<remote setup>', 'exec')
