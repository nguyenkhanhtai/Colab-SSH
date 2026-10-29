"""Unit tests for ML experiment tracking integration (Weights & Biases)."""
import json
import unittest
from unittest.mock import MagicMock, patch

from colab_session.jobs.config import JobConfig, JobConfigDispatcher
from colab_session.jobs.models import Job, JobStatus
from colab_session.tracking.autolog import AutologScriptGenerator, MetricParser
from colab_session.tracking.client import ExperimentTracker, get_tracker
from colab_session.tracking.config import TrackingConfig
from colab_session.tracking.injector import TrackingEnvironmentInjector
import colab_session.server.app as colab_server


class TestMetricParser(unittest.TestCase):

    def test_parse_key_value(self):
        line = "Epoch 1/20 - loss: 0.4215 - accuracy: 0.8920 - val_loss: 0.3812"
        m = MetricParser.parse_line(line)
        self.assertEqual(m["loss"], 0.4215)
        self.assertEqual(m["accuracy"], 0.8920)
        self.assertEqual(m["val_loss"], 0.3812)
        self.assertEqual(m["epoch"], 1)

    def test_parse_json(self):
        line = '{"loss": 0.25, "accuracy": 0.95, "step": 100}'
        m = MetricParser.parse_line(line)
        self.assertEqual(m["loss"], 0.25)
        self.assertEqual(m["accuracy"], 0.95)
        self.assertEqual(m["step"], 100)

    def test_parse_keywords(self):
        line = "step 50: loss 0.1843"
        m = MetricParser.parse_line(line)
        self.assertEqual(m["loss"], 0.1843)
        self.assertEqual(m["step"], 50)


class TestAutologScriptGenerator(unittest.TestCase):

    def test_generate_code_contains_parser_and_wandb(self):
        code = AutologScriptGenerator.generate_code(download_files=["best.pt"])
        self.assertIn("best.pt", code)
        self.assertIn("parse_metrics", code)
        self.assertIn("wandb.init", code)
        self.assertIn("wandb.log", code)


class TestTrackingConfig(unittest.TestCase):

    def test_tracking_config_defaults(self):
        cfg = TrackingConfig(project="solar-detection")
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.provider, "wandb")
        self.assertEqual(cfg.project, "solar-detection")
        self.assertEqual(cfg.mode, "online")

    def test_tracking_config_from_dict_and_aliases(self):
        data = {
            "enabled": True,
            "provider": "wandb",
            "project": "filament-run",
            "name": "run-epoch20",
            "hyperparameters": {"lr": 0.001, "batch_size": 32},
            "tags": ["solar", "t4"],
            "metrics": ["loss", "f1"],
        }
        cfg = TrackingConfig.from_dict(data)
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.run_name, "run-epoch20")
        self.assertEqual(cfg.config["lr"], 0.001)
        self.assertEqual(cfg.tags, ["solar", "t4"])


class TestTrackingEnvironmentInjector(unittest.TestCase):

    def test_injector_wandb(self):
        cfg = TrackingConfig(
            enabled=True,
            provider="wandb",
            project="solar-filament",
            run_name="resnet-v1",
            api_key="wandb_test_key_123",
            tags=["colab", "baseline"],
            config={"epochs": 20, "batch_size": 64},
            metrics=["loss", "acc"],
            auto_install=True,
        )
        env, setup_cmd = TrackingEnvironmentInjector.prepare(cfg)
        self.assertEqual(env["WANDB_PROJECT"], "solar-filament")
        self.assertEqual(env["WANDB_NAME"], "resnet-v1")
        self.assertEqual(env["WANDB_API_KEY"], "wandb_test_key_123")
        self.assertEqual(env["WANDB_TAGS"], "colab,baseline")
        self.assertIn("epochs", env["WANDB_CONFIG"])
        self.assertIn("pip install -q wandb", setup_cmd)

    def test_injector_disabled(self):
        cfg = TrackingConfig(enabled=False)
        env, setup_cmd = TrackingEnvironmentInjector.prepare(cfg)
        self.assertEqual(env, {})
        self.assertIsNone(setup_cmd)


class TestJobConfigWithTracking(unittest.TestCase):

    def test_dispatcher_injects_tracking_into_job_run(self):
        cfg = JobConfig(
            name="train-run",
            gpu="T4",
            command="python3 train.py",
            tracking={
                "enabled": True,
                "provider": "wandb",
                "project": "test-project",
                "run_name": "run-1",
                "api_key": "dummy_key",
                "auto_install": False,
            }
        )
        dispatcher = JobConfigDispatcher(cli="colab-cli")
        dispatcher.resolver.resolve_or_create = MagicMock(return_value=("vm-1", False))
        dispatcher.job_manager.run = MagicMock(return_value=Job(id="job-track", session="vm-1", command="python3 train.py"))

        dispatcher.dispatch(cfg)
        call_args = dispatcher.job_manager.run.call_args[1]
        self.assertEqual(call_args["env"]["WANDB_PROJECT"], "test-project")
        self.assertEqual(call_args["env"]["WANDB_API_KEY"], "dummy_key")


class TestExperimentTrackerClient(unittest.TestCase):

    def test_tracker_offline_graceful_logging(self):
        # Even without wandb installed/authenticated, get_tracker should not crash
        tracker = get_tracker(project="offline-run", config={"lr": 0.01})
        self.assertEqual(tracker.project, "offline-run")
        # Test logging
        tracker.log({"loss": 0.35, "epoch": 1}, step=1)
        tracker.finish()


class TestServerAppTracking(unittest.TestCase):

    def test_server_run_job_with_tracking(self):
        app = colab_server.App("/bin/colab")
        app.job_manager.run = MagicMock(return_value=Job(id="job-serv-1", session="vm-1", command="python3 train.py"))

        payload = {
            "command": "python3 train.py",
            "detached": True,
            "tracking": {
                "enabled": True,
                "provider": "wandb",
                "project": "web-run",
                "api_key": "web_key_999",
                "auto_install": False,
            }
        }
        res = app.run_job("vm-1", payload)
        self.assertEqual(res["id"], "job-serv-1")
        call_args = app.job_manager.run.call_args[1]
        self.assertEqual(call_args["env"]["WANDB_PROJECT"], "web-run")
        self.assertEqual(call_args["env"]["WANDB_API_KEY"], "web_key_999")


if __name__ == "__main__":
    unittest.main()

