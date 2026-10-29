"""Unit tests for JobConfig, SessionResolver, and JobConfigDispatcher."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from colab_session.jobs.config import JobConfig, JobConfigDispatcher
from colab_session.jobs.models import Job, JobStatus
from colab_session.session.resolver import SessionResolver


class TestJobConfig(unittest.TestCase):

    def test_default_values(self):
        cfg = JobConfig()
        self.assertEqual(cfg.name, "colab-job")
        self.assertEqual(cfg.gpu, "T4")
        self.assertTrue(cfg.auto_create)
        self.assertTrue(cfg.detached)
        self.assertEqual(cfg.cwd, "/content")

    def test_to_and_from_dict(self):
        cfg = JobConfig(name="test-run", gpu="L4", command="echo hi")
        d = cfg.to_dict()
        self.assertEqual(d["name"], "test-run")
        self.assertEqual(d["gpu"], "L4")
        self.assertEqual(d["command"], "echo hi")

        loaded = JobConfig.from_dict(d)
        self.assertEqual(loaded.name, "test-run")
        self.assertEqual(loaded.gpu, "L4")

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "job.json"
            cfg = JobConfig(name="file-test", gpu="A100", command="nvidia-smi")
            saved_path = cfg.save(file_path)
            self.assertTrue(saved_path.is_file())

            loaded = JobConfig.load(file_path)
            self.assertEqual(loaded.name, "file-test")
            self.assertEqual(loaded.gpu, "A100")
            self.assertEqual(loaded.command, "nvidia-smi")

    def test_load_not_found(self):
        with self.assertRaises(FileNotFoundError):
            JobConfig.load("/non/existent/path/job.json")

    def test_load_invalid_json(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("{invalid json content")
            f_path = f.name
        try:
            with self.assertRaises(ValueError):
                JobConfig.load(f_path)
        finally:
            Path(f_path).unlink(missing_ok=True)

    def test_template(self):
        tpl = JobConfig.template()
        self.assertEqual(tpl.name, "train-mnist")
        self.assertEqual(tpl.gpu, "T4")
        self.assertTrue(tpl.auto_create)
        self.assertEqual(tpl.command, "python3 -u train.py --epochs 10")
        self.assertIn("results.csv", tpl.download_files)
        self.assertEqual(tpl.download_dir, "./outputs")

    def test_alias_normalization(self):
        data = {
            "name": "alias-test",
            "gpu": "T4",
            "command": "python3 train.py",
            "download": ["model.pt", "log.txt"],
            "output_dir": "./custom_out"
        }
        cfg = JobConfig.from_dict(data)
        self.assertEqual(cfg.download_files, ["model.pt", "log.txt"])
        self.assertEqual(cfg.download_dir, "./custom_out")


class TestSessionResolver(unittest.TestCase):

    def setUp(self):
        self.resolver = SessionResolver(cli="colab-cli")

    @patch("colab_session.session.resolver.list_sessions")
    def test_find_matching_session(self, mock_sessions):
        mock_sessions.return_value = [
            {"name": "colab-gpu-t4", "gpu": "T4", "running": True, "ssh_command": "ssh ..."},
            {"name": "colab-gpu-l4", "gpu": "L4", "running": True, "ssh_command": "ssh ..."},
        ]
        found = self.resolver.find_matching_session("L4")
        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "colab-gpu-l4")

        not_found = self.resolver.find_matching_session("A100")
        self.assertIsNone(not_found)

    @patch("colab_session.session.resolver.list_sessions")
    def test_resolve_or_create_reuses_existing(self, mock_sessions):
        mock_sessions.return_value = [
            {"name": "colab-active-t4", "gpu": "T4", "running": True, "ssh_command": "ssh ..."}
        ]
        session, was_created = self.resolver.resolve_or_create(gpu="T4")
        self.assertEqual(session, "colab-active-t4")
        self.assertFalse(was_created)

    @patch("colab_session.session.provisioner.SessionProvisioner.provision", return_value=0)
    @patch("colab_session.session.resolver.list_sessions")
    def test_resolve_or_create_spins_up_new_when_none_match(self, mock_sessions, mock_provision):
        mock_sessions.return_value = [
            {"name": "colab-active-t4", "gpu": "T4", "running": True, "ssh_command": "ssh ..."}
        ]
        session, was_created = self.resolver.resolve_or_create(gpu="L4", session_name="colab-custom-l4")
        self.assertEqual(session, "colab-custom-l4")
        self.assertTrue(was_created)
        mock_provision.assert_called_once()

    @patch("colab_session.session.resolver.list_sessions")
    def test_resolve_or_create_fails_if_auto_create_disabled(self, mock_sessions):
        mock_sessions.return_value = []
        with self.assertRaises(RuntimeError) as ctx:
            self.resolver.resolve_or_create(gpu="T4", auto_create=False)
        self.assertIn("No running session with GPU 'T4' found", str(ctx.exception))


class TestJobConfigDispatcher(unittest.TestCase):

    def setUp(self):
        self.dispatcher = JobConfigDispatcher(cli="colab-cli")

    def test_dispatch_detached(self):
        cfg = JobConfig(name="test", gpu="T4", command="python3 train.py", detached=True)
        self.dispatcher.resolver.resolve_or_create = MagicMock(return_value=("session-1", False))
        mock_job = Job(id="job-1", session="session-1", command="python3 train.py", status=JobStatus.RUNNING)
        self.dispatcher.job_manager.run = MagicMock(return_value=mock_job)

        session, was_created, res = self.dispatcher.dispatch(cfg)
        self.assertEqual(session, "session-1")
        self.assertFalse(was_created)
        self.assertEqual(res.id, "job-1")
        self.dispatcher.job_manager.run.assert_called_once_with(
            session="session-1",
            command="python3 train.py",
            script_path=None,
            sync_dir=None,
            detached=True,
            cwd="/content",
            download_files=[],
            download_dir=None,
            env={},
            setup_command=None,
            log_file=None,
        )

    def test_save_and_load_yaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "job.yaml"
            cfg = JobConfig(name="yaml-test", gpu="L4", command="python3 test.py", detached=False)
            cfg.save(file_path)
            self.assertTrue(file_path.is_file())

            loaded = JobConfig.load(file_path)
            self.assertEqual(loaded.name, "yaml-test")
            self.assertEqual(loaded.gpu, "L4")
            self.assertFalse(loaded.detached)

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    @patch("colab_session.jobs.config.JobConfigDispatcher.dispatch")
    def test_cli_config_positional(self, mock_dispatch, mock_cli):
        import colab_session.cli.main as cli_main
        mock_dispatch.return_value = ("test-vm", False, (0, "output"))
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "custom_job.json"
            cfg = JobConfig(name="pos-test", gpu="T4", command="echo 1")
            cfg.save(file_path)

            exit_code = cli_main.main([str(file_path)])
            self.assertEqual(exit_code, 0)
            mock_dispatch.assert_called_once()
            called_cfg = mock_dispatch.call_args[0][0]
            self.assertEqual(called_cfg.name, "pos-test")

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    @patch("colab_session.jobs.config.JobConfigDispatcher.dispatch")
    def test_cli_config_flag_with_overrides(self, mock_dispatch, mock_cli):
        import colab_session.cli.main as cli_main
        mock_dispatch.return_value = ("test-vm", False, (0, "output"))
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "custom_job.json"
            cfg = JobConfig(name="flag-test", gpu="T4", command="echo 1")
            cfg.save(file_path)

            exit_code = cli_main.main(["-c", str(file_path), "--gpu", "A100", "-s", "my-session", "--foreground"])
            self.assertEqual(exit_code, 0)
            called_cfg = mock_dispatch.call_args[0][0]
            self.assertEqual(called_cfg.gpu, "A100")
            self.assertEqual(called_cfg.session, "my-session")
            self.assertFalse(called_cfg.detached)

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    @patch("colab_session.jobs.config.JobConfigDispatcher.dispatch")
    def test_cli_config_flag_default_file(self, mock_dispatch, mock_cli):
        import colab_session.cli.main as cli_main
        import os
        mock_dispatch.return_value = ("test-vm", False, (0, "output"))
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "colab-job.json"
            cfg = JobConfig(name="default-test", gpu="T4", command="echo 1")
            cfg.save(file_path)

            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                exit_code = cli_main.main(["-c"])
                self.assertEqual(exit_code, 0)
                mock_dispatch.assert_called_once()
                called_cfg = mock_dispatch.call_args[0][0]
                self.assertEqual(called_cfg.name, "default-test")
            finally:
                os.chdir(old_cwd)

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    @patch("colab_session.jobs.config.JobConfigDispatcher.dispatch")
    def test_cli_job_config_alias(self, mock_dispatch, mock_cli):
        import colab_session.cli.main as cli_main
        mock_dispatch.return_value = ("test-vm", False, (0, "output"))
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "colab-job.json"
            cfg = JobConfig(name="alias-test", gpu="T4", command="echo 1")
            cfg.save(file_path)

            exit_code = cli_main.main(["job", "config", str(file_path)])
            self.assertEqual(exit_code, 0)
            mock_dispatch.assert_called_once()

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    @patch("colab_session.jobs.config.JobConfigDispatcher.dispatch")
    def test_cli_job_run_with_config(self, mock_dispatch, mock_cli):
        import colab_session.cli.main as cli_main
        mock_dispatch.return_value = ("test-vm", False, (0, "output"))
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "colab-job.json"
            cfg = JobConfig(name="run-cfg-test", gpu="T4", command="echo 1", detached=True)
            cfg.save(file_path)

            exit_code = cli_main.main(["job", "run", "-c", str(file_path)])
            self.assertEqual(exit_code, 0)
            called_cfg = mock_dispatch.call_args[0][0]
            # job run forces detached=False
            self.assertFalse(called_cfg.detached)

    @patch("colab_session.cli.main.find_colab_cli", return_value="/bin/colab")
    @patch("colab_session.jobs.config.JobConfigDispatcher.dispatch")
    def test_cli_job_submit_with_config(self, mock_dispatch, mock_cli):
        import colab_session.cli.main as cli_main
        mock_job = Job(id="job-99", session="test-vm", command="echo 1", status=JobStatus.RUNNING)
        mock_dispatch.return_value = ("test-vm", False, mock_job)
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "colab-job.json"
            cfg = JobConfig(name="sub-cfg-test", gpu="T4", command="echo 1", detached=False)
            cfg.save(file_path)

            exit_code = cli_main.main(["job", "submit", "-c", str(file_path)])
            self.assertEqual(exit_code, 0)
            called_cfg = mock_dispatch.call_args[0][0]
            # job submit forces detached=True
            self.assertTrue(called_cfg.detached)


if __name__ == "__main__":
    unittest.main()
