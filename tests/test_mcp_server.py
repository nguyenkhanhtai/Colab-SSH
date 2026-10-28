"""Unit tests for Colab Model Context Protocol (MCP) server."""
import io
import json
import unittest
from unittest.mock import MagicMock, patch

from colab_session.jobs.models import Job, JobStatus
from colab_session.mcp.server import ColabMCPServer


class TestColabMCPServer(unittest.TestCase):

    def setUp(self):
        self.server = ColabMCPServer(cli="fake-colab")

    def test_initialize(self):
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"}
        }
        res = self.server.handle_request(req)
        self.assertEqual(res["id"], 1)
        self.assertIn("capabilities", res["result"])
        self.assertEqual(res["result"]["serverInfo"]["name"], "colab-ssh-mcp")

    def test_initialized_notification(self):
        req = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {}
        }
        res = self.server.handle_request(req)
        self.assertIsNone(res)

    def test_tools_list(self):
        req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        }
        res = self.server.handle_request(req)
        self.assertEqual(res["id"], 2)
        tools = res["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        self.assertIn("colab_list_sessions", tool_names)
        self.assertIn("colab_resolve_session", tool_names)
        self.assertIn("colab_run_job", tool_names)
        self.assertIn("colab_run_from_config", tool_names)
        self.assertIn("colab_get_job_status", tool_names)
        self.assertIn("colab_get_job_logs", tool_names)
        self.assertIn("colab_stop_job", tool_names)
        self.assertIn("colab_backup_session", tool_names)
        self.assertIn("colab_stop_session", tool_names)
        self.assertIn("colab_download_files", tool_names)
        self.assertIn("colab_pull_job_artifacts", tool_names)

    @patch("colab_session.mcp.server.list_sessions")
    def test_call_list_sessions(self, mock_sessions):
        mock_sessions.return_value = [
            {"name": "colab-gpu-1", "gpu": "T4", "ssh_command": "ssh -F ~/.ssh/colab colab-gpu-1"}
        ]
        req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "colab_list_sessions", "arguments": {}}
        }
        res = self.server.handle_request(req)
        self.assertEqual(res["id"], 3)
        text = res["result"]["content"][0]["text"]
        self.assertIn("colab-gpu-1", text)
        self.assertIn("T4", text)

    def test_call_resolve_session(self):
        self.server.resolver.resolve_or_create = MagicMock(return_value=("colab-reused", False))
        req = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "colab_resolve_session", "arguments": {"gpu": "L4"}}
        }
        res = self.server.handle_request(req)
        data = json.loads(res["result"]["content"][0]["text"])
        self.assertEqual(data["session"], "colab-reused")
        self.assertFalse(data["was_created"])
        self.assertEqual(data["status"], "ready")
        self.server.resolver.resolve_or_create.assert_called_once_with(gpu="L4", session_name=None, auto_create=True)

    def test_call_run_job_detached(self):
        mock_job = Job(id="job-abc", session="colab-test", command="nvidia-smi", status=JobStatus.RUNNING)
        self.server.job_manager.run = MagicMock(return_value=mock_job)

        req = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "colab_run_job",
                "arguments": {
                    "session": "colab-test",
                    "command": "nvidia-smi",
                    "detached": True
                }
            }
        }
        res = self.server.handle_request(req)
        data = json.loads(res["result"]["content"][0]["text"])
        self.assertEqual(data["id"], "job-abc")
        self.assertEqual(data["status"], "running")

    def test_call_run_job_foreground(self):
        self.server.job_manager.run = MagicMock(return_value=(0, "GPU: Tesla T4\n"))

        req = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "colab_run_job",
                "arguments": {
                    "session": "colab-test",
                    "command": "nvidia-smi",
                    "detached": False
                }
            }
        }
        res = self.server.handle_request(req)
        data = json.loads(res["result"]["content"][0]["text"])
        self.assertEqual(data["exit_code"], 0)
        self.assertIn("Tesla T4", data["output"])

    def test_call_run_from_config(self):
        mock_job = Job(id="job-cfg-1", session="colab-auto", command="python3 train.py", status=JobStatus.RUNNING)
        self.server.dispatcher.dispatch = MagicMock(return_value=("colab-auto", True, mock_job))

        with patch("colab_session.jobs.config.JobConfig.load") as mock_load:
            mock_cfg = MagicMock()
            mock_cfg.name = "mnist"
            mock_cfg.gpu = "T4"
            mock_load.return_value = mock_cfg

            req = {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "colab_run_from_config",
                    "arguments": {"config_path": "colab-job.json"}
                }
            }
            res = self.server.handle_request(req)
            data = json.loads(res["result"]["content"][0]["text"])
            self.assertEqual(data["id"], "job-cfg-1")
            self.assertEqual(data["session"], "colab-auto")
            self.assertTrue(data["was_created"])

    def test_call_job_status_and_logs(self):
        mock_job = Job(id="job-status-1", session="colab-test", command="ls", status=JobStatus.COMPLETED, exit_code=0)
        self.server.job_manager.status = MagicMock(return_value=mock_job)
        self.server.job_manager.logs = MagicMock(return_value="file1.txt\nfile2.txt\n")

        # Status
        req_status = {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {"name": "colab_get_job_status", "arguments": {"session": "colab-test", "job_id": "job-status-1"}}
        }
        res_status = self.server.handle_request(req_status)
        data_status = json.loads(res_status["result"]["content"][0]["text"])
        self.assertEqual(data_status["status"], "completed")

        # Logs
        req_logs = {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": "colab_get_job_logs", "arguments": {"session": "colab-test", "job_id": "job-status-1", "tail": 50}}
        }
        res_logs = self.server.handle_request(req_logs)
        self.assertIn("file1.txt", res_logs["result"]["content"][0]["text"])

    def test_call_stop_job(self):
        self.server.job_manager.stop = MagicMock(return_value=True)
        req = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "colab_stop_job", "arguments": {"session": "s1", "job_id": "j1"}}
        }
        res = self.server.handle_request(req)
        data = json.loads(res["result"]["content"][0]["text"])
        self.assertTrue(data["stopped"])
        self.assertEqual(data["job_id"], "j1")

    @patch("colab_session.mcp.server.backup_session")
    def test_call_backup_session(self, mock_backup):
        mock_backup.return_value = {"key": "backup-key-12345"}
        req = {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {"name": "colab_backup_session", "arguments": {"session": "s1"}}
        }
        res = self.server.handle_request(req)
        self.assertIn("backup-key-12345", res["result"]["content"][0]["text"])

    @patch("colab_session.mcp.server.stop_session")
    def test_call_stop_session(self, mock_stop):
        req = {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {"name": "colab_stop_session", "arguments": {"session": "s1"}}
        }
        res = self.server.handle_request(req)
        data = json.loads(res["result"]["content"][0]["text"])
        self.assertEqual(data["status"], "stopped")
        self.assertEqual(data["session"], "s1")
        mock_stop.assert_called_once_with(self.server.cli, "s1")

    def test_call_download_files(self):
        self.server.job_manager.download_files = MagicMock(return_value=["model.pt", "log.txt"])
        req = {
            "jsonrpc": "2.0",
            "id": 121,
            "method": "tools/call",
            "params": {
                "name": "colab_download_files",
                "arguments": {
                    "session": "s1",
                    "files": ["model.pt", "log.txt"],
                    "dest_dir": "./output"
                }
            }
        }
        res = self.server.handle_request(req)
        data = json.loads(res["result"]["content"][0]["text"])
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["downloaded_files"], ["model.pt", "log.txt"])
        self.server.job_manager.download_files.assert_called_once_with(
            "s1", ["model.pt", "log.txt"], local_dest_dir="./output", remote_cwd="/content"
        )

    def test_call_pull_job_artifacts(self):
        self.server.job_manager.pull = MagicMock(return_value=["weights.pt"])
        req = {
            "jsonrpc": "2.0",
            "id": 122,
            "method": "tools/call",
            "params": {
                "name": "colab_pull_job_artifacts",
                "arguments": {
                    "session": "s1",
                    "job_id": "job-999"
                }
            }
        }
        res = self.server.handle_request(req)
        data = json.loads(res["result"]["content"][0]["text"])
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["downloaded_artifacts"], ["weights.pt"])
        self.server.job_manager.pull.assert_called_once_with("s1", "job-999", local_dest_dir=None)

    def test_ping(self):
        req = {"jsonrpc": "2.0", "id": 13, "method": "ping"}
        res = self.server.handle_request(req)
        self.assertEqual(res["result"], {})

    def test_unknown_method(self):
        req = {"jsonrpc": "2.0", "id": 14, "method": "non_existent_method"}
        res = self.server.handle_request(req)
        self.assertEqual(res["error"]["code"], -32601)

    def test_tool_execution_error(self):
        self.server.resolver.resolve_or_create = MagicMock(side_effect=RuntimeError("Quota exceeded"))
        req = {
            "jsonrpc": "2.0",
            "id": 15,
            "method": "tools/call",
            "params": {"name": "colab_resolve_session", "arguments": {"gpu": "A100"}}
        }
        res = self.server.handle_request(req)
        self.assertTrue(res["result"]["isError"])
        self.assertIn("Quota exceeded", res["result"]["content"][0]["text"])

    def test_serve_stdio(self):
        input_data = json.dumps({"jsonrpc": "2.0", "id": 99, "method": "ping"}) + "\n"
        with patch("sys.stdin", io.StringIO(input_data)):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                self.server.serve_stdio()
                output = mock_stdout.getvalue()
                res = json.loads(output.strip())
                self.assertEqual(res["id"], 99)
                self.assertEqual(res["result"], {})


if __name__ == "__main__":
    unittest.main()
