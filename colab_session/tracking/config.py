"""Configuration schema for ML experiment tracking platforms."""
from dataclasses import asdict, dataclass, field
import os
from typing import Any, Dict, List, Optional


@dataclass
class TrackingConfig:
    """Experiment tracking options for remote ML runs (Weights & Biases, etc.)."""
    enabled: bool = True
    provider: str = "wandb"
    project: str = "colab-experiments"
    entity: Optional[str] = None
    run_name: Optional[str] = None
    api_key: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    metrics: List[str] = field(default_factory=list)
    auto_install: bool = True
    mode: str = "online"
    autolog: bool = True
    sync_tensorboard: bool = True
    log_artifacts: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["TrackingConfig"]:
        if not data:
            return None
        raw = dict(data)
        # Normalize aliases
        if "name" in raw and "run_name" not in raw:
            raw["run_name"] = raw.pop("name")
        if "hyperparameters" in raw and "config" not in raw:
            raw["config"] = raw.pop("hyperparameters")
        allowed = cls.__annotations__
        filtered = {k: v for k, v in raw.items() if k in allowed}
        return cls(**filtered)

    def resolved_api_key(self) -> Optional[str]:
        """Resolve API key from explicit config or environment."""
        if self.api_key:
            return self.api_key
        if self.provider == "wandb":
            return os.environ.get("WANDB_API_KEY")
        return None

