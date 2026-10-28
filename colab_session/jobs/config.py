"""Declarative configuration file loader and dispatcher for Colab jobs."""
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from colab_session.jobs.manager import JobManager
from colab_session.jobs.models import Job
from colab_session.session.resolver import SessionResolver


@dataclass
class JobConfig:
    """Declarative configuration model for a remote job."""
    name: str = "colab-job"
    gpu: str = "T4"
    session: Optional[str] = None
    auto_create: bool = True
    command: str = ""
    script: Optional[str] = None
    sync_dir: Optional[str] = None
    cwd: str = "/content"
    detached: bool = True
    mount_drive: bool = False
    download_files: List[str] = field(default_factory=list)
    download_dir: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobConfig":
        raw = dict(data)
        # Normalize common aliases
        if "download" in raw and "download_files" not in raw:
            raw["download_files"] = raw.pop("download")
        elif "artifacts" in raw and "download_files" not in raw:
            raw["download_files"] = raw.pop("artifacts")
        if "output_dir" in raw and "download_dir" not in raw:
            raw["download_dir"] = raw.pop("output_dir")

        allowed = cls.__annotations__
        filtered = {k: v for k, v in raw.items() if k in allowed}
        return cls(**filtered)

    @classmethod
    def load(cls, path: Path | str) -> "JobConfig":
        """Load job configuration from a JSON file."""
        target = Path(path).expanduser().resolve()
        if not target.is_file():
            raise FileNotFoundError(f"Configuration file not found: {target}")
        try:
            content = json.loads(target.read_text(encoding="utf-8"))
            return cls.from_dict(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in configuration file {target}: {exc}") from exc

    def save(self, path: Path | str) -> Path:
        """Write job configuration to a JSON file."""
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return target

    @classmethod
    def template(cls) -> "JobConfig":
        """Return a starter template configuration."""
        return cls(
            name="train-mnist",
            gpu="T4",
            session=None,
            auto_create=True,
            command="python3 -u train.py --epochs 10",
            script="train.py",
            sync_dir=None,
            cwd="/content",
            detached=True,
            mount_drive=False,
            download_files=["checkpoints/model.pt", "results.csv"],
            download_dir="./outputs",
        )


class JobConfigDispatcher:
    """Orchestrates session lookup/creation and job submission based on JobConfig."""

    def __init__(self, cli: str):
        self.cli = cli
        self.resolver = SessionResolver(cli)
        self.job_manager = JobManager(cli)

    def dispatch(self, config: JobConfig) -> Tuple[str, bool, Any]:
        """
        Executes the job workflow:
        1. Checks if a session with the required GPU is running.
        2. Reuses it, or provisions a new one if not running.
        3. Executes the specified command/script on that session.
        Returns: (session_name, was_created, job_or_result).
        """
        session_name, was_created = self.resolver.resolve_or_create(
            gpu=config.gpu,
            session_name=config.session,
            auto_create=config.auto_create,
            mount_drive=config.mount_drive,
        )

        cmd = config.command
        if not cmd and not config.script:
            # If no command or script specified, simply return the resolved session
            return session_name, was_created, None

        result = self.job_manager.run(
            session=session_name,
            command=cmd,
            script_path=config.script,
            sync_dir=config.sync_dir,
            detached=config.detached,
            cwd=config.cwd,
            download_files=config.download_files,
            download_dir=config.download_dir,
        )
        return session_name, was_created, result

