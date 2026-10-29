"""Unit tests for remote filesystem explorer and log path resolution."""
from datetime import datetime
import io
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from colab_session.cli import main as cli_main
from colab_session.jobs.models import resolve_log_file
from colab_session.session.explorer import RemoteDirectoryExplorer


class TestLogResolution(unittest.TestCase):

    def test_resolve_default_log_file(self):
        p = resolve_log_file("my-colab-vm", date_str="2026-10-28")
        self.assertEqual(p.parts[:3], ("logs", "my-colab-vm", "2026-10-28"))
        self.assertTrue(p.name.startswith("job_"))
        self.assertTrue(p.name.endswith(".log"))

    def test_resolve_with_job_id(self):
        p = resolve_log_file("my-colab-vm", job_id="job-abc123", date_str="2026-10-28")
        self.assertEqual(p, Path("logs/my-colab-vm/2026-10-28/job-abc123.log"))

    def test_resolve_with_custom_name(self):
        p = resolve_log_file("my-colab-vm", log_file="train.log", date_str="2026-10-28")
        self.assertEqual(p, Path("logs/my-colab-vm/2026-10-28/train.log"))

    def test_resolve_nested_logs_relative(self):
        p = resolve_log_file("my-colab-vm", log_file="logs/my-colab-vm/2026-10-28/output.log", date_str="2026-10-28")
        self.assertEqual(p, Path("logs/my-colab-vm/2026-10-28/output.log"))

    def test_resolve_absolute_path(self):
        p = resolve_log_file("my-colab-vm", log_file="/tmp/custom.log")
        self.assertEqual(p, Path("/tmp/custom.log"))


class TestRemoteDirectoryExplorer(unittest.TestCase):

    def test_render_tree_basic(self):
        tree = {
            "name": "content",
            "path": "/content",
            "is_dir": True,
            "children": [
                {
                    "name": "checkpoints",
                    "path": "/content/checkpoints",
                    "is_dir": True,
                    "children": [
                        {"name": "best.pt", "path": "/content/checkpoints/best.pt", "is_dir": False, "size_human": "50.0 MB"}
                    ],
                    "has_more": False,
                },
                {"name": "train.py", "path": "/content/train.py", "is_dir": False, "size_human": "4.2 KB"}
            ],
            "has_more": False,
        }
        output = RemoteDirectoryExplorer.render_tree(tree)
        self.assertIn("/content/", output)
        self.assertIn("├── checkpoints/", output)
        self.assertIn("│   └── best.pt (50.0 MB)", output)
        self.assertIn("└── train.py (4.2 KB)", output)

    def test_render_tree_capped_10_items_has_more(self):
        tree = {
            "name": "models",
            "path": "/content/models",
            "is_dir": True,
            "children": [
                {"name": f"model_{i}.pt", "is_dir": False, "size_human": "10 MB"} for i in range(10)
            ],
            "has_more": True,
            "remaining_count": 25,
        }
        output = RemoteDirectoryExplorer.render_tree(tree)
        self.assertIn("model_0.pt (10 MB)", output)
        self.assertIn("model_9.pt (10 MB)", output)
        self.assertIn("└── ... (+25 more items)", output)

    @patch("colab_session.session.explorer.subprocess.run")
    @patch("colab_session.session.explorer.ssh_command_for_session", return_value=["ssh", "test-vm"])
    def test_inspect_tree(self, mock_ssh, mock_run):
        mock_tree = {"path": "/content", "is_dir": True, "children": []}
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(mock_tree), stderr="")

        explorer = RemoteDirectoryExplorer(cli="colab-cli")
        result = explorer.inspect_tree("test-vm", path="/content", max_depth=3, max_items_per_branch=10)
        self.assertEqual(result["path"], "/content")
        mock_run.assert_called_once()
        cmd_arg = mock_run.call_args[0][0][-1]
        self.assertIn("python3 -", cmd_arg)
        self.assertIn("/content 3 10 0", cmd_arg)
        self.assertIn("scan_dir", mock_run.call_args[1]["input"])

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    @patch("colab_session.jobs.manager.JobManager.tree")
    def test_cli_job_tree(self, mock_tree, mock_cli):
        mock_tree.return_value = {
            "path": "/content",
            "is_dir": True,
            "children": [{"name": "script.py", "is_dir": False, "size_human": "1 KB"}],
        }
        with patch("sys.stdout", io.StringIO()) as out:
            code = cli_main.main(["job", "tree", "--session", "test-vm", "/content"])
        self.assertEqual(code, 0)
        mock_tree.assert_called_once_with("test-vm", path="/content", max_depth=2, max_items=10, show_hidden=False)
        self.assertIn("script.py (1 KB)", out.getvalue())

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    @patch("colab_session.jobs.manager.JobManager.tree")
    def test_cli_root_tree(self, mock_tree, mock_cli):
        mock_tree.return_value = {
            "path": "/content",
            "is_dir": True,
            "children": [],
        }
        with patch("sys.stdout", io.StringIO()) as out:
            code = cli_main.main(["--session", "test-vm", "--tree"])
        self.assertEqual(code, 0)
        mock_tree.assert_called_once_with("test-vm", path="/content", max_depth=2, max_items=10)
        self.assertIn("/content/", out.getvalue())


if __name__ == "__main__":
    unittest.main()
