import json
from pathlib import Path
import tempfile
import unittest
from credentials import read_auth, read_pat, save_pat_mapping


class CredentialTests(unittest.TestCase):
    def test_relative_pat_path_is_resolved_against_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'github.pat').write_text('test-token\n')
            config = root / 'auth.json'
            config.write_text('{"github_pat_file":"github.pat"}')
            self.assertEqual(read_auth(config), 'test-token')

    def test_repository_mapping_selects_matching_pat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'alpha.pat').write_text('alpha-secret')
            (root / 'beta.pat').write_text('beta-secret')
            config = root / 'auth.json'
            config.write_text(json.dumps({
                'github_repositories': {
                    'https://github.com/Owner/Alpha.git': 'alpha.pat',
                    'https://github.com/owner/beta': 'beta.pat',
                }
            }))
            self.assertEqual(read_auth(config, 'https://github.com/owner/alpha'), 'alpha-secret')
            self.assertEqual(read_auth(config, 'https://github.com/OWNER/BETA.git'), 'beta-secret')
            self.assertEqual(read_auth(config, 'https://github.com/owner/other'), '')
            self.assertEqual(read_auth(config), '')

    def test_saved_pat_mapping_is_private_and_reusable(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'auth.json'
            first = save_pat_mapping('https://github.com/Owner/Alpha.git', 'alpha-secret', config)
            second = save_pat_mapping('https://github.com/owner/beta', 'beta-secret', config)
            self.assertEqual(read_auth(config, 'https://github.com/owner/alpha'), 'alpha-secret')
            self.assertEqual(read_auth(config, 'https://github.com/OWNER/BETA.git'), 'beta-secret')
            self.assertEqual(first.stat().st_mode & 0o777, 0o600)
            self.assertEqual(second.stat().st_mode & 0o777, 0o600)
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            mapping = json.loads(config.read_text())['github_repositories']
            self.assertEqual(len(mapping), 2)
            self.assertNotIn('alpha-secret', config.read_text())
            self.assertNotIn('beta-secret', config.read_text())

    def test_bad_files_fail_without_echoing_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'token.pat'
            for value in ['', 'secret one\nsecret two']:
                file.write_text(value)
                with self.assertRaises(ValueError) as err:
                    read_pat(file)
                self.assertNotIn('secret', str(err.exception))
            file.write_text('{"github_pat_file": "secret" BROKEN}')
            with self.assertRaises(ValueError) as err:
                read_auth(file)
            self.assertNotIn('secret', str(err.exception))

    def test_scoped_token_is_not_used_for_other_repositories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'github.pat').write_text('repo-secret')
            config = root / 'auth.json'
            config.write_text('{"github_pat_file":"github.pat", "github_repository":"https://github.com/owner/private.git"}')
            self.assertEqual(read_auth(config, 'https://github.com/OWNER/private'), 'repo-secret')
            self.assertEqual(read_auth(config, 'https://github.com/owner/another.git'), '')
            self.assertEqual(read_auth(config), '')
            (root / 'github.pat').unlink()
            self.assertEqual(read_auth(config, 'https://github.com/owner/another.git'), '')
