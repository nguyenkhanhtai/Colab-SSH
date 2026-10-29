"""Declarative configuration file loader and dispatcher for Colab jobs."""
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from colab_session.jobs.manager import JobManager
from colab_session.jobs.models import Job, format_job_manifest, validate_job_requirements
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
    env: Dict[str, str] = field(default_factory=dict)
    setup_command: Optional[str] = None
    tracking: Optional[Dict[str, Any]] = None
    log_file: Optional[str] = None

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
        if "environment" in raw and "env" not in raw:
            raw["env"] = raw.pop("environment")
        if "setup" in raw and "setup_command" not in raw:
            raw["setup_command"] = raw.pop("setup")
        if "log" in raw and "log_file" not in raw:
            raw["log_file"] = raw.pop("log")
        elif "log_path" in raw and "log_file" not in raw:
            raw["log_file"] = raw.pop("log_path")

        allowed = cls.__annotations__
        filtered = {k: v for k, v in raw.items() if k in allowed}
        return cls(**filtered)

    @classmethod
    def load(cls, path: Path | str) -> "JobConfig":
        """Load job configuration from a JSON or YAML file."""
        target = Path(path).expanduser().resolve()
        if not target.is_file():
            # If default name was requested or not found, check alternate extensions
            if target.name in ("colab-job.json", "colab-job"):
                yaml_alt = target.with_name("colab-job.yaml")
                yml_alt = target.with_name("colab-job.yml")
                if yaml_alt.is_file():
                    target = yaml_alt
                elif yml_alt.is_file():
                    target = yml_alt
                else:
                    raise FileNotFoundError(f"Configuration file not found: {path} (checked .json, .yaml, .yml)")
            else:
                raise FileNotFoundError(f"Configuration file not found: {target}")

        raw_text = target.read_text(encoding="utf-8")
        if target.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml
                content = yaml.safe_load(raw_text)
                if not isinstance(content, dict):
                    raise ValueError(f"Configuration in {target} must be a YAML mapping/dictionary")
                return cls.from_dict(content)
            except Exception as exc:
                raise ValueError(f"Invalid YAML in configuration file {target}: {exc}") from exc

        try:
            content = json.loads(raw_text)
            return cls.from_dict(content)
        except json.JSONDecodeError as exc:
            # Attempt YAML fallback
            try:
                import yaml
                content = yaml.safe_load(raw_text)
                if isinstance(content, dict):
                    return cls.from_dict(content)
            except Exception:
                pass
            raise ValueError(f"Invalid JSON/YAML in configuration file {target}: {exc}") from exc

    def save(self, path: Path | str) -> Path:
        """Write job configuration to a JSON or YAML file."""
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix.lower() in (".yaml", ".yml"):
            import yaml
            target.write_text(yaml.safe_dump(self.to_dict(), sort_keys=False) + "\n", encoding="utf-8")
        else:
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
            log_file="./logs/train.log",
            tracking={
                "enabled": True,
                "provider": "wandb",
                "project": "solar-filament-detection",
                "run_name": "baseline-experiment",
                "config": {"epochs": 10, "lr": 0.001, "batch_size": 32},
                "metrics": ["loss", "accuracy"]
            },
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

        validate_job_requirements(
            command=cmd,
            script_path=config.script,
            sync_dir=config.sync_dir,
            session=session_name,
        )

        manifest = format_job_manifest(
            session=session_name,
            command=cmd,
            script_path=config.script,
            sync_dir=config.sync_dir,
            cwd=config.cwd,
            detached=config.detached,
            download_files=config.download_files,
            download_dir=config.download_dir,
            log_file=config.log_file,
            gpu=config.gpu,
            env=config.env,
            setup_command=config.setup_command,
            tracking=config.tracking,
        )
        print(manifest, flush=True)

        merged_env = dict(config.env)
        merged_setup = config.setup_command
        if config.tracking:
            from colab_session.tracking.injector import TrackingEnvironmentInjector
            track_env, track_setup = TrackingEnvironmentInjector.prepare(config.tracking)
            merged_env.update(track_env)
            if track_setup:
                merged_setup = f"{track_setup} && {merged_setup}" if merged_setup else track_setup

        result = self.job_manager.run(
            session=session_name,
            command=cmd,
            script_path=config.script,
            sync_dir=config.sync_dir,
            detached=config.detached,
            cwd=config.cwd,
            download_files=config.download_files,
            download_dir=config.download_dir,
            env=merged_env,
            setup_command=merged_setup,
            log_file=config.log_file,
        )
        return session_name, was_created, result

