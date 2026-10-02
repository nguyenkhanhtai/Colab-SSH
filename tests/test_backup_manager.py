import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch, MagicMock

import backup_manager


class BackupManagerTests(unittest.TestCase):
    def test_generate_key_format(self):
        k1 = backup_manager.generate_key()
        k2 = backup_manager.generate_key()
        self.assertTrue(k1.startswith("bk-"))
        self.assertTrue(k2.startswith("bk-"))
        self.assertNotEqual(k1, k2)
        self.assertEqual(len(k1), 11)  # "bk-" + 8 hex chars

    def test_validate_key(self):
        self.assertEqual(backup_manager.validate_key("bk-1234abcd"), "bk-1234abcd")
        self.assertEqual(backup_manager.validate_key("custom_key-01"), "custom_key-01")
        for invalid in ["", "   ", "key with space", "key/slash", "key$var", "../traversal"]:
            with self.assertRaises(ValueError):
                backup_manager.validate_key(invalid)

    def test_remote_code_compiles(self):
        code_backup = backup_manager.backup_remote_code("session-test", "bk-1234abcd")
        compile(code_backup, "<string>", "exec")
        self.assertIn("bk-1234abcd", code_backup)
        self.assertIn("MyDrive", code_backup)
        self.assertIn("tar", code_backup)

        code_restore = backup_manager.restore_remote_code("bk-1234abcd")
        compile(code_restore, "<string>", "exec")
        self.assertIn("bk-1234abcd", code_restore)
        self.assertIn("MyDrive", code_restore)
        self.assertIn("tar", code_restore)

        code_list = backup_manager.list_backups_remote_code()
        compile(code_list, "<string>", "exec")
        self.assertIn("MyDrive", code_list)

    @patch("backup_manager.ssh_command_for_session", return_value=["ssh", "root@session-1"])
    @patch("backup_manager.subprocess.run")
    def test_backup_success(self, run, ssh_cmd):
        run.return_value = MagicMock(
            return_value=0,
            stdout="Some ssh banner\n" + json.dumps({
                "status": "ok",
                "key": "bk-1234abcd",
                "size_mb": 15.5,
                "path": "/content/drive/MyDrive/Colab-Backups/bk-1234abcd.tar.gz"
            }) + "\n"
        )
        res = backup_manager.backup("/bin/colab", "session-1", key="bk-1234abcd")
        self.assertEqual(res["key"], "bk-1234abcd")
        self.assertEqual(res["size_mb"], 15.5)
        run.assert_called_once()
        self.assertEqual(run.call_args[0][0][0], "ssh")

    @patch("backup_manager.ssh_command_for_session", return_value=["ssh", "root@session-1"])
    @patch("backup_manager.subprocess.run")
    def test_backup_drive_not_mounted_fails_clearly(self, run, ssh_cmd):
        run.side_effect = subprocess.CalledProcessError(
            1, "ssh", stderr="RuntimeError: Google Drive is not mounted in this session."
        )
        with self.assertRaises(RuntimeError) as ctx:
            backup_manager.backup("/bin/colab", "session-1", key="bk-1234abcd")
        self.assertIn("Google Drive is not mounted", str(ctx.exception))

    @patch("backup_manager.ssh_command_for_session", return_value=["ssh", "root@session-1"])
    @patch("backup_manager.subprocess.run")
    def test_list_backups_success(self, run, ssh_cmd):
        items = [{"key": "bk-1", "size_mb": 10}, {"key": "bk-2", "size_mb": 20}]
        run.return_value = MagicMock(
            return_value=0,
            stdout=json.dumps({"status": "ok", "backups": items}) + "\n"
        )
        res = backup_manager.list_backups("/bin/colab", "session-1")
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]["key"], "bk-1")


if __name__ == "__main__":
    unittest.main()

