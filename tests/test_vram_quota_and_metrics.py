"""Tests for VRAM Quota management, Hard Cap enforcement, Timeout, and Session Metrics."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from colab_session.jobs.models import Job, JobStatus, format_job_manifest
from colab_session.jobs.quota import check_session_vram_capacity, parse_timeout_to_seconds, parse_vram_to_mb
from colab_session.metrics.collector import format_metrics_table, get_session_metrics
from colab_session.session.resolver import SessionResolver


class TestVramAndQuotaParsing(unittest.TestCase):
    def test_parse_vram(self):
        self.assertIsNone(parse_vram_to_mb(None))
        self.assertIsNone(parse_vram_to_mb(""))
        self.assertEqual(parse_vram_to_mb(8192), 8192)
        self.assertEqual(parse_vram_to_mb("8GB"), 8192)
        self.assertEqual(parse_vram_to_mb("8gb"), 8192)
        self.assertEqual(parse_vram_to_mb("4G"), 4096)
        self.assertEqual(parse_vram_to_mb("500MB"), 500)
        self.assertEqual(parse_vram_to_mb("500M"), 500)
        self.assertEqual(parse_vram_to_mb("8192"), 8192)
        self.assertEqual(parse_vram_to_mb("1.5GB"), 1536)

        with self.assertRaises(ValueError):
            parse_vram_to_mb("-8GB")
        with self.assertRaises(ValueError):
            parse_vram_to_mb("invalid")

    def test_parse_timeout(self):
        self.assertIsNone(parse_timeout_to_seconds(None))
        self.assertIsNone(parse_timeout_to_seconds(""))
        self.assertEqual(parse_timeout_to_seconds(3600), 3600)
        self.assertEqual(parse_timeout_to_seconds("1h"), 3600)
        self.assertEqual(parse_timeout_to_seconds("1.5h"), 5400)
        self.assertEqual(parse_timeout_to_seconds("30m"), 1800)
        self.assertEqual(parse_timeout_to_seconds("45s"), 45)
        self.assertEqual(parse_timeout_to_seconds("3600"), 3600)

        with self.assertRaises(ValueError):
            parse_timeout_to_seconds("0s")
        with self.assertRaises(ValueError):
            parse_timeout_to_seconds("bad")


class TestJobManifestAndStatus(unittest.TestCase):
    def test_manifest_shows_vram_and_timeout(self):
        manifest = format_job_manifest(
            session="test-vm",
            command="python3 train.py",
            vram="8GB",
            timeout="1h",
        )
        self.assertIn("• VRAM Hard Cap : 8GB", manifest)
        self.assertIn("• Timeout Limit : 1h", manifest)

    def test_job_timed_out_status(self):
        from colab_session.jobs.runner import RemoteJobRunner

        runner = RemoteJobRunner(cli="colab")
        runner._ssh_command = MagicMock(return_value=["ssh", "mock"])

        # Mock stdout for query_status returning TIMED_OUT and exit 124
        mock_stdout = (
            '{"id": "job-1", "session": "test-vm", "command": "run.sh"}\n'
            '---STATUS---\n'
            'STARTED 2026-10-31T00:00:00Z\n'
            'TIMED_OUT 2026-10-31T01:00:00Z\n'
            'EXIT 124 2026-10-31T01:00:00Z\n'
            '---PID---\n'
            'DEAD\n'
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=mock_stdout)
            job = runner.get_job_status("test-vm", "job-1")
            self.assertEqual(job.status, JobStatus.TIMED_OUT.value)
            self.assertEqual(job.exit_code, 124)


class TestSessionResolverVramCapacity(unittest.TestCase):
    @patch("colab_session.session.resolver.list_sessions")
    @patch("colab_session.jobs.quota.check_session_vram_capacity")
    def test_reject_session_with_insufficient_vram(self, mock_check, mock_list):
        mock_list.return_value = [{"name": "colab-busy", "gpu": "T4", "running": True}]
        # Only 2000MB available, but job requests 8GB (8192MB)
        mock_check.return_value = (False, 2000, 15360)

        resolver = SessionResolver(cli="colab")
        # auto_create=False should raise GpuAllocationError
        with self.assertRaises(Exception) as ctx:
            resolver.resolve_or_create(gpu="T4", vram="8GB", auto_create=False)
        self.assertIn("sufficient available VRAM", str(ctx.exception))

    @patch("colab_session.session.resolver.list_sessions")
    @patch("colab_session.jobs.quota.check_session_vram_capacity")
    def test_reuse_session_with_sufficient_vram(self, mock_check, mock_list):
        mock_list.return_value = [{"name": "colab-ready", "gpu": "T4", "running": True}]
        # 10000MB available >= 8192MB
        mock_check.return_value = (True, 10000, 15360)

        resolver = SessionResolver(cli="colab")
        sess_name, was_created = resolver.resolve_or_create(gpu="T4", vram="8GB", auto_create=False)
        self.assertEqual(sess_name, "colab-ready")
        self.assertFalse(was_created)


class TestSessionMetrics(unittest.TestCase):
    def test_format_metrics_table(self):
        sample_metrics = {
            "session": "colab-test",
            "gpu": {
                "name": "Tesla T4",
                "util_pct": 35,
                "memory_used_mb": 4096,
                "memory_total_mb": 15360,
                "temperature_c": 68,
            },
            "cpu": {"load_1m": 0.45, "load_5m": 0.30},
            "ram": {"total_mb": 12000, "available_mb": 8000, "used_mb": 4000},
            "quota": {
                "total_vram_mb": 15360,
                "allocated_vram_mb": 4096,
                "available_vram_mb": 11264,
                "allocations": {"job-test": {"vram_mb": 4096, "pid": 1234}},
            },
        }
        table = format_metrics_table(sample_metrics)
        self.assertIn("Tesla T4", table)
        self.assertIn("35% utilization", table)
        self.assertIn("4,096 MB / 15,360 MB", table)
        self.assertIn("11,264 MB (Headroom for new jobs)", table)
        self.assertIn("job-test: 4,096 MB", table)


if __name__ == "__main__":
    unittest.main()
