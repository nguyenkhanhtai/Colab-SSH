"""Lightweight, resilient experiment tracker helper for ML training scripts."""
import json
import os
from typing import Any, Dict, Optional


class ExperimentTracker:
    """Wrapper that logs metrics to Weights & Biases if configured, with graceful local fallback."""

    def __init__(
        self,
        project: Optional[str] = None,
        name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.project = project or os.environ.get("WANDB_PROJECT", "colab-run")
        self.name = name or os.environ.get("WANDB_NAME")
        self.config = config or {}
        raw_config = os.environ.get("WANDB_CONFIG")
        if raw_config and not self.config:
            try:
                self.config = json.loads(raw_config)
            except Exception:
                pass

        self._wandb = None
        self._run = None
        try:
            import wandb
            self._wandb = wandb
            self._run = wandb.init(
                project=self.project,
                name=self.name,
                config=self.config,
                resume="allow",
            )
            print(f"[Tracker] Initialized Weights & Biases run: {self._run.name} ({getattr(self._run, 'url', '')})")
        except Exception as exc:
            print(f"[Tracker] Notice: Running in offline local logging mode ({exc})")

    def log(self, metrics: Dict[str, Any], step: Optional[int] = None) -> None:
        """Log a metric dictionary (e.g. {'epoch': 1, 'loss': 0.24, 'accuracy': 0.95})."""
        if self._wandb and self._run:
            self._wandb.log(metrics, step=step)
        else:
            step_str = f" [Step {step}]" if step is not None else ""
            metric_str = ", ".join(f"{k}: {v}" for k, v in metrics.items())
            print(f"[Metric]{step_str} {metric_str}")

    def finish(self) -> None:
        """Finalize run tracking."""
        if self._wandb and self._run:
            self._wandb.finish()


def get_tracker(
    project: Optional[str] = None,
    name: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> ExperimentTracker:
    """Return an ExperimentTracker instance initialized from environment or parameters."""
    return ExperimentTracker(project=project, name=name, config=config)

