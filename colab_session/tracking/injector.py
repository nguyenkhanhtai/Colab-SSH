"""Translates tracking configurations into runtime environment variables and setup commands."""
import json
from typing import Dict, List, Optional, Tuple

from colab_session.tracking.config import TrackingConfig


class TrackingEnvironmentInjector:
    """Injects experiment tracking configuration (WandB / MLflow) into remote job execution."""

    @classmethod
    def prepare(cls, tracking: Optional[TrackingConfig | Dict]) -> Tuple[Dict[str, str], Optional[str]]:
        """
        Returns:
            (env_vars_dict, setup_command_string)
        """
        if not tracking:
            return {}, None

        cfg = tracking if isinstance(tracking, TrackingConfig) else TrackingConfig.from_dict(tracking)
        if not cfg or not cfg.enabled:
            return {}, None

        env: Dict[str, str] = {}
        setup_cmds: List[str] = []

        if cfg.provider.lower() == "wandb":
            api_key = cfg.resolved_api_key()
            if api_key:
                env["WANDB_API_KEY"] = api_key
            if cfg.project:
                env["WANDB_PROJECT"] = cfg.project
            if cfg.entity:
                env["WANDB_ENTITY"] = cfg.entity
            if cfg.run_name:
                env["WANDB_NAME"] = cfg.run_name
            if cfg.tags:
                env["WANDB_TAGS"] = ",".join(str(t).strip() for t in cfg.tags if str(t).strip())
            if cfg.mode:
                env["WANDB_MODE"] = cfg.mode
            if cfg.config:
                env["WANDB_CONFIG"] = json.dumps(cfg.config)
            if cfg.metrics:
                env["WANDB_METRICS"] = ",".join(cfg.metrics)

            if cfg.auto_install:
                setup_cmds.append("python3 -c 'import wandb' 2>/dev/null || pip install -q wandb")

        setup_str = " && ".join(setup_cmds) if setup_cmds else None
        return env, setup_str

