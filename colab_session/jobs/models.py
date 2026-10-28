"""Data models for remote job execution on Colab."""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import secrets
from typing import Any, Dict, List, Optional


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

