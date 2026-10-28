"""Unit tests for remote file downloading and artifact extraction."""
from io import BytesIO
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from colab_session.jobs.runner import JobFileSynchronizer, RemoteJobRunner
from colab_session.jobs.models import Job, JobStatus


class TestJobFileDownloader(unittest.TestCase):

    def test_download_empty_list_returns_early(self):
        result = JobFileSynchronizer.download_files_or_dirs(
            ssh_cmd=["ssh", "host"],
            remote_paths=[],
            local_dest_dir="./downloads"
        )
        self.assertEqual(result, [])

    @patch("colab_session.jobs.runner.subprocess.run")
    def test_download_no_match_returns_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"NO_MATCH\n")
        with tempfile.TemporaryDirectory() as tmp:
            result = JobFileSynchronizer.download_files_or_dirs(
                ssh_cmd=["ssh", "host"],
                remote_paths=["nonexistent.txt"],
                local_dest_dir=tmp,
            )
            self.assertEqual(result, [])

    @patch("colab_session.jobs.runner.subprocess.run")
    def test_download_extracts_files_safely(self, mock_run):
        archive_buffer = BytesIO()
        with tarfile.open(fileobj=archive_buffer, mode="w:gz") as tar:
            data = b"model weights binary data"
            info = tarfile.TarInfo(name="model.pt")
            info.size = len(data)
            tar.addfile(info, BytesIO(data))

            csv_data = b"loss,epoch\n0.1,1\n"
            csv_info = tarfile.TarInfo(name="results/metrics.csv")
            csv_info.size = len(csv_data)
            tar.addfile(csv_info, BytesIO(csv_data))

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=archive_buffer.getvalue(),
            stderr=b"FOUND:model.pt,results/metrics.csv\n"
        )

        with tempfile.TemporaryDirectory() as tmp:
            downloaded = JobFileSynchronizer.download_files_or_dirs(
                ssh_cmd=["ssh", "host"],
                remote_paths=["model.pt", "results/*.csv"],
                local_dest_dir=tmp,
                remote_base_dir="/content",
            )
            self.assertEqual(downloaded, ["model.pt", "results/metrics.csv"])
            dest = Path(tmp)
            self.assertTrue((dest / "model.pt").is_file())
            self.assertEqual((dest / "model.pt").read_bytes(), b"model weights binary data")
            self.assertTrue((dest / "results" / "metrics.csv").is_file())
            self.assertEqual((dest / "results" / "metrics.csv").read_bytes(), b"loss,epoch\n0.1,1\n")

    @patch("colab_session.jobs.runner.subprocess.run")
    def test_download_prevents_path_traversal(self, mock_run):
        archive_buffer = BytesIO()
        with tarfile.open(fileobj=archive_buffer, mode="w:gz") as tar:
            data = b"malicious content"
            info = tarfile.TarInfo(name="../../etc/passwd")
            info.size = len(data)
            tar.addfile(info, BytesIO(data))

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=archive_buffer.getvalue(),
            stderr=b"FOUND:../../etc/passwd\n"
        )

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as ctx:
                JobFileSynchronizer.download_files_or_dirs(
                    ssh_cmd=["ssh", "host"],
                    remote_paths=["../../etc/passwd"],
                    local_dest_dir=tmp,
                )
            self.assertIn("Unsafe path detected", str(ctx.exception))

    @patch("colab_session.jobs.runner.RemoteJobRunner.download_files", return_value=["weights.pt"])
    def test_runner_pull_job_artifacts(self, mock_dl):
        runner = RemoteJobRunner(cli="colab-cli")
        mock_job = Job(
            id="job-pull-1",
            session="vm-test",
            command="python3 train.py",
            download_files=["weights.pt"],
            download_dir="./checkpoints",
            cwd="/content/my_model",
        )
        runner.get_job_status = MagicMock(return_value=mock_job)

        downloaded = runner.pull_job_artifacts("vm-test", "job-pull-1")
        self.assertEqual(downloaded, ["weights.pt"])
        mock_dl.assert_called_once_with(
            "vm-test",
            remote_paths=["weights.pt"],
            local_dest_dir="./checkpoints",
            remote_base_dir="/content/my_model",
        )


if __name__ == "__main__":
    unittest.main()

