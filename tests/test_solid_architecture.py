"""Unit tests verifying newly refactored SOLID classes and object-oriented design."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from colab_session.auth.credentials import CredentialManager, ITokenReader, RepositoryIdentifier, TokenFileReader
from colab_session.hardware.gpu import GPUConfigurator, GPUHardwareVerifier, GPULibraryConfigurator
from colab_session.ssh.config import SSHConfigManager, SSHNaming
from colab_session.storage.backup import BackupKeyManager, BackupScriptGenerator, DriveBackupService
from colab_session.session.manager import ColabCliClient, SessionManager, SessionStateStore, ColabCliFinder
from colab_session.env.environment import ContextSynchronizer, JSONCParser, VSCodeProfileManager
from colab_session.session.provisioner import SessionConfig, SessionProvisioner, WorkspaceScriptGenerator
from colab_session.server.app import LogStatusParser


class SolidArchitectureTests(unittest.TestCase):
    def test_repository_identifier(self):
        owner, repo = RepositoryIdentifier.parse("https://github.com/Google/Antigravity.git")
        self.assertEqual(owner, "google")
        self.assertEqual(repo, "antigravity")
        canonical = RepositoryIdentifier.canonical_url("google", "antigravity")
        self.assertEqual(canonical, "https://github.com/google/antigravity")

    def test_credential_manager_with_injected_reader(self):
        class MockReader(ITokenReader):
            def read_token(self, path):
                return "mock-token-from-reader"

        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "auth.json"
            config_file.write_text(json.dumps({
                "github_repositories": {
                    "https://github.com/test-org/test-repo": "custom.pat"
                }
            }))
            manager = CredentialManager(config_path=config_file, token_reader=MockReader())
            token = manager.resolve_token("https://github.com/test-org/test-repo.git")
            self.assertEqual(token, "mock-token-from-reader")

    def test_ssh_naming_and_config_manager_di(self):
        self.assertEqual(SSHNaming.alias("custom"), "colab-custom")
        self.assertEqual(SSHNaming.alias("colab-custom"), "colab-custom")
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            mgr = SSHConfigManager(config_home=home)
            self.assertEqual(mgr.config_home, home)
            self.assertEqual(mgr.ssh_dir, home / "ssh")
            self.assertEqual(mgr.alias_for("my-vm"), "colab-my-vm")
            self.assertEqual(mgr.config_for("my-vm"), home / "ssh/my-vm.conf")

    def test_backup_key_manager_and_script_generator(self):
        key = BackupKeyManager.generate()
        self.assertEqual(BackupKeyManager.validate(key), key)
        code = BackupScriptGenerator.backup_script("test-session", key)
        self.assertIn("tar", code)
        self.assertIn(key, code)

    def test_session_state_store_and_manager_di(self):
        store = SessionStateStore()
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "sessions.json"
            state_path.write_text(json.dumps({
                "vm1": {"running": True, "accelerator": "T4"},
                "vm2": {"running": False, "accelerator": "L4"},
            }))
            active = store.active_names(state_path)
            self.assertEqual(active, {"vm1"})

    def test_jsonc_parser_handles_comments(self):
        parsed = JSONCParser.parse('{"setting": true, /* block comment */ // inline\n "num": 42,}')
        self.assertEqual(parsed, {"setting": True, "num": 42})

    def test_workspace_script_generator(self):
        script = WorkspaceScriptGenerator.prepare_workspace_code("/content/my-dir", "drive")
        self.assertIn("/content/my-dir", script)
        self.assertIn("drive", script)

    def test_log_status_parser_stages(self):
        status, stage, progress, awaiting, auth_url = LogStatusParser.parse("Creating runtime...", None, False)
        self.assertEqual(status, "provisioning")
        self.assertEqual(stage, "Creating runtime")
        self.assertEqual(progress, 8)
        self.assertFalse(awaiting)
        self.assertIsNone(auth_url)


if __name__ == "__main__":
    unittest.main()

