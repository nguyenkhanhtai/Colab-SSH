"""Unit tests for Colab remote job execution, tracking, and CLI commands."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from colab_session.jobs.manager import JobManager
from colab_session.jobs.models import Job, JobStatus
from colab_session.jobs.runner import JobFileSynchronizer, JobScriptGenerator, RemoteJobRunner
import colab_session.cli.main as app
import colab_session.server.app as colab_server


class JobRunnerTests(unittest.TestCase):
    def test_job_model_lifecycle(self):
        job = Job(id="job-1234", session="my-session", command="python3 train.py")
        self.assertEqual(job.id, "job-1234")
        self.assertEqual(job.session, "my-session")
        self.assertEqual(job.status, JobStatus.QUEUED.value)
        self.assertEqual(job.log_path, "/root/.colab-jobs/job-1234.log")

        data = job.to_dict()
        reconstructed = Job.from_dict(data)
        self.assertEqual(reconstructed.id, job.id)
        self.assertEqual(reconstructed.command, job.command)

    def test_script_generator_contains_status_and_pid(self):
        wrapper = JobScriptGenerator.wrapper_script(
            "job-9999",
            "echo hello",
            cwd="/content/repo",
            env={"CUSTOM_VAR": "42"},
            setup_command="pip install -q torch",
        )
        self.assertIn("/root/.colab-jobs/job-9999.status", wrapper)
        self.assertIn("/root/.colab-jobs/job-9999.pid", wrapper)
        self.assertIn("cd /content/repo", wrapper)
        self.assertIn("echo hello", wrapper)
        self.assertIn("EXIT $EXIT_CODE", wrapper)
        self.assertIn("/usr/lib64-nvidia", wrapper)
        self.assertIn("/root/.local/bin", wrapper)
        self.assertIn("export CUSTOM_VAR=42", wrapper)
        self.assertIn("pip install -q torch", wrapper)

    @patch("colab_session.jobs.runner.subprocess.run")
    def test_file_synchronizer_creates_tarball(self, run):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "train.py"
            script.write_text("print('training...')")
            remote_path = JobFileSynchronizer.sync_file_or_dir(["ssh", "root@host"], script, remote_dest_dir="/content")
            self.assertEqual(remote_path, "/content/train.py")
            run.assert_called_once()
            args = run.call_args
            self.assertIn("tar -xzf - -C /content", args[0][0][-1])
            self.assertIn("input", args[1])

    @patch("colab_session.jobs.runner.ssh_command_for_session", return_value=["ssh", "root@session-1"])
    @patch("colab_session.jobs.runner.subprocess.run")
    def test_run_sync_foreground(self, run, ssh_cmd):
        run.return_value = MagicMock(returncode=0, stdout="output from run\n", stderr="")
        runner = RemoteJobRunner(cli="/bin/colab")
        exit_code, out = runner.run_sync("session-1", "nvidia-smi", capture_output=True)
        self.assertEqual(exit_code, 0)
        self.assertIn("output from run", out)
        run.assert_called_once()
        self.assertIn("cd /content && nvidia-smi", run.call_args[0][0][-1])

    @patch("colab_session.jobs.runner.ssh_command_for_session", return_value=["ssh", "root@session-1"])
    @patch("colab_session.jobs.runner.subprocess.run")
    def test_submit_detached_creates_background_job(self, run, ssh_cmd):
        runner = RemoteJobRunner(cli="/bin/colab")
        job = runner.submit_detached("session-1", "python3 -u train.py", cwd="/content/my_project")
        self.assertTrue(job.id.startswith("job-"))
        self.assertEqual(job.session, "session-1")
        self.assertEqual(job.status, JobStatus.RUNNING.value)
        run.assert_called_once()
        stdin_content = run.call_args[1]["input"]
        self.assertIn("nohup", stdin_content)
        self.assertIn(job.id, stdin_content)

    @patch("colab_session.jobs.runner.ssh_command_for_session", return_value=["ssh", "root@session-1"])
    @patch("colab_session.jobs.runner.subprocess.run")
    def test_get_job_status_running_and_completed(self, run, ssh_cmd):
        runner = RemoteJobRunner(cli="/bin/colab")

        # Mock 1: process is alive
        run.return_value = MagicMock(
            stdout=json.dumps({"id": "job-1", "session": "session-1", "command": "run.sh"})
            + "\n---STATUS---\nSTARTED 2026-10-28T07:00:00Z\n---PID---\n12345\nALIVE\n"
        )
        job = runner.get_job_status("session-1", "job-1")
        self.assertEqual(job.status, JobStatus.RUNNING.value)
        self.assertEqual(job.started_at, "2026-10-28T07:00:00Z")

        # Mock 2: process completed with exit code 0
        run.return_value = MagicMock(
            stdout=json.dumps({"id": "job-1", "session": "session-1", "command": "run.sh"})
            + "\n---STATUS---\nSTARTED 2026-10-28T07:00:00Z\nEXIT 0 2026-10-28T07:10:00Z\n---PID---\n12345\nDEAD\n"
        )
        job_done = runner.get_job_status("session-1", "job-1")
        self.assertEqual(job_done.status, JobStatus.COMPLETED.value)
        self.assertEqual(job_done.exit_code, 0)
        self.assertEqual(job_done.completed_at, "2026-10-28T07:10:00Z")

    @patch("colab_session.jobs.runner.ssh_command_for_session", return_value=["ssh", "root@session-1"])
    @patch("colab_session.jobs.runner.subprocess.run")
    def test_get_job_logs(self, run, ssh_cmd):
        run.return_value = MagicMock(stdout="Epoch 1/10: loss 0.42\nEpoch 2/10: loss 0.21\n")
        runner = RemoteJobRunner(cli="/bin/colab")
        logs = runner.get_job_logs("session-1", "job-1", tail=50)
        self.assertIn("Epoch 1/10", logs)
        self.assertIn("tail -n 50", run.call_args[0][0][-1])

    @patch("colab_session.jobs.runner.ssh_command_for_session", return_value=["ssh", "root@session-1"])
    @patch("colab_session.jobs.runner.subprocess.run")
    def test_stop_job(self, run, ssh_cmd):
        run.return_value = MagicMock(stdout="STOPPED\n")
        runner = RemoteJobRunner(cli="/bin/colab")
        success = runner.stop_job("session-1", "job-1")
        self.assertTrue(success)

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    @patch("colab_session.jobs.manager.RemoteJobRunner.run_sync", return_value=(0, "ok"))
    def test_cli_job_run(self, run_sync, which):
        with patch("sys.stdout", io.StringIO()):
            code = app.main(["job", "run", "--session", "test-vm", "nvidia-smi"])
        self.assertEqual(code, 0)
        run_sync.assert_called_once_with(
            session="test-vm",
            command="nvidia-smi",
            script_path=None,
            sync_dir=None,
            cwd="/content",
            capture_output=False,
            download_files=None,
            download_dir="./downloads",
            env=None,
            setup_command=None,
            log_file=None,
        )

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    @patch("colab_session.jobs.manager.RemoteJobRunner.run_sync", return_value=(0, "ok"))
    def test_cli_job_run_with_log_file(self, run_sync, which):
        with patch("sys.stdout", io.StringIO()):
            code = app.main(["job", "run", "--session", "test-vm", "--log-file", "output.log", "nvidia-smi"])
        self.assertEqual(code, 0)
        run_sync.assert_called_once_with(
            session="test-vm",
            command="nvidia-smi",
            script_path=None,
            sync_dir=None,
            cwd="/content",
            capture_output=False,
            download_files=None,
            download_dir="./downloads",
            env=None,
            setup_command=None,
            log_file="output.log",
        )

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    @patch("colab_session.jobs.manager.RemoteJobRunner.submit_detached")
    def test_cli_job_submit(self, submit_detached, which):
        mock_job = Job(id="job-abc1", session="test-vm", command="python train.py")
        submit_detached.return_value = mock_job
        with patch("sys.stdout", io.StringIO()) as out:
            code = app.main(["job", "submit", "--session", "test-vm", "python train.py"])
        self.assertEqual(code, 0)
        self.assertIn("job-abc1", out.getvalue())

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    @patch("colab_session.jobs.manager.RemoteJobRunner.run_sync", return_value=(0, "ok"))
    def test_cli_run_shortcut(self, run_sync, which):
        code = app.main(["--run", "nvidia-smi", "--session", "test-vm"])
        self.assertEqual(code, 0)
        run_sync.assert_called_once()

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    def test_cli_job_init_config(self, which):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "custom-job.json"
            code = app.main(["job", "init-config", str(cfg_path)])
            self.assertEqual(code, 0)
            self.assertTrue(cfg_path.is_file())
            content = json.loads(cfg_path.read_text())
            self.assertEqual(content["name"], "train-mnist")
            self.assertEqual(content["gpu"], "T4")

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    @patch("colab_session.jobs.config.JobConfigDispatcher.dispatch")
    def test_cli_job_run_config(self, mock_dispatch, which):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "job.json"
            cfg_path.write_text(json.dumps({"name": "test-job", "gpu": "T4", "command": "echo 1"}))
            mock_job = Job(id="job-run-cfg", session="vm-1", command="echo 1")
            mock_dispatch.return_value = ("vm-1", False, mock_job)

            with patch("sys.stdout", io.StringIO()) as out:
                code = app.main(["job", "run-config", str(cfg_path)])
            self.assertEqual(code, 0)
            self.assertIn("job-run-cfg", out.getvalue())
            self.assertIn("Reusing active", out.getvalue())

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    @patch("colab_session.jobs.config.JobConfigDispatcher.dispatch")
    def test_cli_config_flag(self, mock_dispatch, which):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "job.json"
            cfg_path.write_text(json.dumps({"name": "test-job", "gpu": "T4", "command": "echo 1"}))
            mock_job = Job(id="job-flag-1", session="vm-2", command="echo 1")
            mock_dispatch.return_value = ("vm-2", True, mock_job)

            with patch("sys.stdout", io.StringIO()) as out:
                code = app.main(["--config", str(cfg_path)])
            self.assertEqual(code, 0)
            self.assertIn("job-flag-1", out.getvalue())
            self.assertIn("Created new", out.getvalue())

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    @patch("colab_session.jobs.manager.JobManager.download_files", return_value=["model.pt", "results.csv"])
    def test_cli_job_download(self, mock_download, which):
        with patch("sys.stdout", io.StringIO()) as out:
            code = app.main(["job", "download", "model.pt", "results.csv", "--session", "test-vm", "--dest", "./outputs"])
        self.assertEqual(code, 0)
        self.assertIn("Successfully downloaded 2 item(s)", out.getvalue())
        mock_download.assert_called_once_with("test-vm", ["model.pt", "results.csv"], local_dest_dir="./outputs", remote_cwd="/content")

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    @patch("colab_session.jobs.manager.JobManager.pull", return_value=["checkpoint.pt"])
    def test_cli_job_pull(self, mock_pull, which):
        with patch("sys.stdout", io.StringIO()) as out:
            code = app.main(["job", "pull", "job-1234", "--session", "test-vm"])
        self.assertEqual(code, 0)
        self.assertIn("Successfully pulled 1 artifact(s)", out.getvalue())
        mock_pull.assert_called_once_with("test-vm", "job-1234", local_dest_dir=None)

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    @patch("colab_session.jobs.manager.JobManager.download_files", return_value=["output.png"])
    def test_cli_top_level_download(self, mock_download, which):
        with patch("sys.stdout", io.StringIO()) as out:
            code = app.main(["--session", "test-vm", "--download", "output.png", "--dest", "./my_images"])
        self.assertEqual(code, 0)
        self.assertIn("Successfully downloaded 1 item(s)", out.getvalue())
        mock_download.assert_called_once_with("test-vm", ["output.png"], local_dest_dir="./my_images")

    def test_server_job_api_endpoints(self):
        app_instance = colab_server.App("/bin/colab")
        app_instance.run_job = MagicMock(return_value={"id": "job-123", "status": "running"})
        handler_cls = colab_server.handler_for(app_instance)
        handler = handler_cls.__new__(handler_cls)
        raw_body = json.dumps({"command": "nvidia-smi", "detached": True}).encode()
        handler.headers = {"Content-Length": str(len(raw_body))}
        handler.rfile = io.BytesIO(raw_body)
        handler.path = "/api/sessions/test-vm/jobs"

        replied = {}
        def mock_reply(data, status=200):
            replied["data"] = data
            replied["status"] = status
        handler.reply = mock_reply
        handler.validate_origin = lambda: True

        handler.do_POST()
        self.assertEqual(replied["status"], 200)
        self.assertEqual(replied["data"]["id"], "job-123")
        app_instance.run_job.assert_called_once_with("test-vm", {"command": "nvidia-smi", "detached": True})

    def test_validate_job_requirements(self):
        from colab_session.exceptions import ColabSessionError, PreflightValidationError
        from colab_session.jobs.models import format_job_manifest, validate_job_requirements

        # Missing both command and script
        with self.assertRaises(PreflightValidationError) as ctx:
            validate_job_requirements(command="", script_path=None, session="test-vm")
        self.assertIn("Missing required execution target", str(ctx.exception))
        self.assertTrue(issubclass(PreflightValidationError, ColabSessionError))
        self.assertTrue(issubclass(PreflightValidationError, ValueError))

        # Missing script file
        with self.assertRaises(FileNotFoundError) as ctx:
            validate_job_requirements(command="python3 non_existent.py", script_path="non_existent_file.py", session="test-vm")
        self.assertIn("Local script file not found", str(ctx.exception))

        # Missing sync directory
        with self.assertRaises(NotADirectoryError) as ctx:
            validate_job_requirements(command="ls", sync_dir="/non/existent/dir/12345", session="test-vm")
        self.assertIn("Local sync directory not found", str(ctx.exception))

        # Empty session name
        with self.assertRaises(ValueError) as ctx:
            validate_job_requirements(command="ls", session="   ")
        self.assertIn("session name cannot be empty", str(ctx.exception))

        # Valid parameters succeed without raising
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "main.py"
            script.write_text("print(1)")
            validate_job_requirements(command="", script_path=script, sync_dir=tmp, session="test-vm")

    def test_format_job_manifest(self):
        from colab_session.jobs.models import format_job_manifest
        manifest = format_job_manifest(
            session="colab-gpu-node",
            gpu="A100",
            command="python3 train.py --lr 0.001",
            script_path="train.py",
            sync_dir="./src",
            cwd="/content/my_project",
            detached=True,
            download_files=["checkpoints/model.pt", "eval.json"],
            download_dir="./weights",
            log_file="logs/my_run.log",
            env={"BATCH_SIZE": "64", "SECRET_KEY": "supersecret"},
            setup_command="pip install -q transformers",
            tracking={"enabled": True, "provider": "wandb", "project": "filament", "run_name": "run-42", "metrics": ["loss", "acc"]},
        )
        self.assertIn("COLAB JOB EXECUTION MANIFEST", manifest)
        self.assertIn("colab-gpu-node", manifest)
        self.assertIn("A100", manifest)
        self.assertIn("Background (Detached)", manifest)
        self.assertIn("/content/my_project", manifest)
        self.assertIn("train.py", manifest)
        self.assertIn("./src -> /content/my_project", manifest)
        self.assertIn("pip install -q transformers", manifest)
        self.assertIn("checkpoints/model.pt, eval.json -> ./weights", manifest)
        self.assertIn("WANDB (Project: 'filament', Run: 'run-42')", manifest)
        self.assertIn("loss, acc", manifest)
        self.assertIn("BATCH_SIZE = 64", manifest)
        self.assertIn("SECRET_KEY = ***", manifest)

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    def test_cli_job_preflight_validation_failure(self, which):
        with patch("sys.stderr", io.StringIO()) as err:
            code = app.main(["job", "run", "--session", "test-vm"])
        self.assertEqual(code, 1)
        self.assertIn("Pre-flight requirement check failed", err.getvalue())
        self.assertIn("Missing required execution target", err.getvalue())


if __name__ == "__main__":
    unittest.main()

