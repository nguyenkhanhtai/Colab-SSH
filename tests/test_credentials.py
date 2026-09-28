from pathlib import Path
import tempfile
import unittest
from credentials import read_auth, read_pat


class CredentialTests(unittest.TestCase):
    def test_relative_pat_path_is_resolved_against_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'github.pat').write_text('test-token\n')
            config = root / 'auth.json'
            config.write_text('{"github_pat_file":"github.pat"}')
            self.assertEqual(read_auth(config), 'test-token')

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
