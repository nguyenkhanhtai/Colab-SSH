"""Data models for remote job execution on Colab."""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import secrets
from typing import Any, Dict, List, Optional

from colab_session.exceptions import PreflightValidationError


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class Job:
    """Represents a remote job executed on a Colab session."""
    id: str
    session: str
    command: str
    status: str = JobStatus.QUEUED.value
    created_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    exit_code: Optional[int] = None
    pid: Optional[int] = None
    log_path: str = ""
    cwd: Optional[str] = None
    download_files: List[str] = field(default_factory=list)
    download_dir: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)
    setup_command: Optional[str] = None
    log_file: Optional[str] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.log_path:
            self.log_path = f"/root/.colab-jobs/{self.id}.log"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})

    @classmethod
    def create_id(cls) -> str:
        return f"job-{secrets.token_hex(4)}"


def resolve_log_file(
    session: str,
    log_file: Optional[str | Path] = None,
    job_id: Optional[str] = None,
    date_str: Optional[str] = None,
) -> Path:
    """
    Resolve local log file path according to convention:
    logs/<session_name>/<date>/<filename>
    """
    date_part = date_str or datetime.now().strftime("%Y-%m-%d")
    base_dir = Path("logs") / session / date_part

    if not log_file:
        file_name = f"{job_id}.log" if job_id else f"job_{datetime.now().strftime('%H%M%S')}.log"
        return base_dir / file_name

    p = Path(log_file)
    if p.is_absolute():
        return p

    parts = p.parts
    if len(parts) >= 3 and parts[0] == "logs" and parts[1] == session:
        return p

    file_name = p.name if p.suffix else f"{p.name}.log"
    return base_dir / file_name


def validate_job_requirements(
    command: Optional[str] = None,
    script_path: Optional[str | Path] = None,
    sync_dir: Optional[str | Path] = None,
    session: Optional[str] = None,
) -> None:
    """Validate that required parameters for job execution are present and valid."""
    cmd_clean = (command or "").strip()
    if not cmd_clean and not script_path:
        raise PreflightValidationError(
            "Missing required execution target: You must provide either a shell 'command' (e.g. 'nvidia-smi'), "
            "a local script path ('--script train.py'), or a configuration file ('--config colab-job.json')."
        )
    if script_path:
        p = Path(script_path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Local script file not found: '{script_path}' (resolved: {p})")
    if sync_dir:
        p = Path(sync_dir).expanduser().resolve()
        if not p.is_dir():
            raise NotADirectoryError(f"Local sync directory not found: '{sync_dir}' (resolved: {p})")
    if session is not None and not session.strip():
        raise PreflightValidationError("Target session name cannot be empty.")


def format_job_manifest(
    session: str,
    command: Optional[str] = None,
    script_path: Optional[str | Path] = None,
    sync_dir: Optional[str | Path] = None,
    cwd: str = "/content",
    detached: bool = False,
    download_files: Optional[List[str]] = None,
    download_dir: Optional[str | Path] = None,
    log_file: Optional[str | Path] = None,
    gpu: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    setup_command: Optional[str] = None,
    tracking: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate a clean, structured manifest describing everything required and configured for the job execution."""
    lines = [
        "╔════════════════════════════════════════════════════════════════════════════╗",
        "║                     COLAB JOB EXECUTION MANIFEST                           ║",
        "╚════════════════════════════════════════════════════════════════════════════╝",
        "[Target & Session]",
        f"  • Session Name  : {session}" + (f" (GPU: {gpu})" if gpu else ""),
        f"  • Execution Mode: {'Background (Detached)' if detached else 'Foreground (Synchronous)'}",
        f"  • Remote CWD    : {cwd}",
        "",
        "[Execution Target]",
    ]
    if script_path:
        lines.append(f"  • Local Script  : {script_path} (Uploaded to {cwd}/{Path(script_path).name})")
    if sync_dir:
        lines.append(f"  • Local Sync Dir: {sync_dir} -> {cwd}")
    if command:
        lines.append(f"  • Command       : {command}")
    elif script_path:
        lines.append(f"  • Command       : python3 {Path(script_path).name}")

    if setup_command:
        lines.append(f"  • Setup Command : {setup_command}")

    resolved_log = resolve_log_file(session, log_file)
    lines.extend([
        "",
        "[Outputs & Logging]",
        f"  • Terminal Log  : {resolved_log}",
    ])
    if download_files:
        lines.append(f"  • Pull Artifacts: {', '.join(download_files)} -> {download_dir or './downloads'}")
    else:
        lines.append("  • Pull Artifacts: None")

    if tracking and tracking.get("enabled", True):
        provider = tracking.get("provider", "wandb")
        proj = tracking.get("project", "default")
        run_name = tracking.get("run_name", "unnamed")
        lines.extend([
            "",
            "[Telemetry & Experiment Tracking]",
            f"  • Platform      : {provider.upper()} (Project: '{proj}', Run: '{run_name}')",
        ])
        if tracking.get("metrics"):
            lines.append(f"  • Tracked Metrics: {', '.join(tracking['metrics'])}")

    if env:
        lines.extend([
            "",
            "[Environment Variables]",
        ])
        for k, v in env.items():
            masked_v = "***" if any(sec in k.lower() for sec in ("key", "secret", "token", "password")) else v
            lines.append(f"  • {k} = {masked_v}")

    lines.append("═" * 78)
    return "\n".join(lines)


