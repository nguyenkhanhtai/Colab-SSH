from io import BytesIO
import json
from pathlib import Path
import tempfile
import tarfile
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


    def test_context_sync_uses_allowlist_and_excludes_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / '.codex/rules').mkdir(parents=True)
            (home / '.codex/skills/user').mkdir(parents=True)
            (home / '.codex/skills/.system').mkdir(parents=True)
            (home / '.codex/sessions/2026/09').mkdir(parents=True)
            (home / '.gemini/antigravity/conversations').mkdir(parents=True)
            (home / '.gemini/antigravity-ide/conversations').mkdir(parents=True)
            (home / '.codex/AGENTS.md').write_text('instructions')
            (home / '.codex/sessions/2026/09/session.jsonl').write_text('conversation')
            (home / '.codex/auth.json').write_text('secret')
            (home / '.codex/rules/default.rules').write_text('rule')
            (home / '.codex/skills/user/SKILL.md').write_text('skill')
            (home / '.codex/skills/user/auth.json').write_text('secret')
            (home / '.codex/skills/.system/secret.txt').write_text('secret')
            (home / '.gemini/GEMINI.md').write_text('gemini context')
            (home / '.gemini/antigravity/conversations/chat.pb').write_text('cli chat')
            (home / '.gemini/antigravity-ide/conversations/chat.pb').write_text('ide chat')
            with patch('setup_environment.subprocess.run') as run:
                copied = env.sync_context(['ssh', 'root@test'], home)
            archive = run.call_args.kwargs['input']
            with tarfile.open(fileobj=BytesIO(archive), mode='r:gz') as bundle:
                names = bundle.getnames()
            self.assertIn('.codex/AGENTS.md', names)
            self.assertNotIn('.codex/rules/default.rules', names)
            self.assertIn('.codex/skills/user/SKILL.md', names)
            self.assertIn('.gemini/GEMINI.md', names)
            self.assertIn('.codex/sessions/2026/09/session.jsonl', names)
            self.assertIn('.gemini/antigravity/conversations/chat.pb', names)
            self.assertIn('.gemini/antigravity-ide/conversations/chat.pb', names)
            self.assertFalse(any('auth.json' in name for name in names))
            self.assertFalse(any('/.system' in name for name in names))
            self.assertNotIn('.codex/auth.json', copied)
    def test_remote_program_compiles(self):
        compile(env.remote_code(), '<remote setup>', 'exec')
