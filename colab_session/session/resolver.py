"""Session resolver for auto-reusing active sessions with matching GPU or auto-creating new ones."""
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from colab_session.exceptions import ColabSessionError, GpuAllocationError, SessionProvisioningError
from colab_session.session.manager import sessions as list_sessions, validate_name
from colab_session.session.provisioner import SessionConfig, SessionProvisioner


class SessionResolver:
    """Finds an existing active session with matching GPU or provisions a new one (Single Responsibility)."""

    def __init__(self, cli: str):
        self.cli = cli

    def find_matching_session(self, gpu: str, prefer_session: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Search active sessions for one having the requested GPU type."""
        active = list_sessions(cli=self.cli)
        gpu_target = (gpu or "T4").strip().upper()
        matching = []

        for s in active:
            if not s.get("running"):
                continue
            sess_gpu = str(s.get("gpu") or "").strip().upper()
            if sess_gpu == gpu_target or (gpu_target == "G4" and "G4" in sess_gpu):
                matching.append(s)

        if not matching:
            return None

        if prefer_session:
            for s in matching:
                if s["name"] == prefer_session:
                    return s

        return matching[0]

    def resolve_or_create(
        self,
        gpu: str = "T4",
        session_name: Optional[str] = None,
        auto_create: bool = True,
        mount_drive: bool = False,
        repo_url: Optional[str] = None,
        repo_name: Optional[str] = None,
        branch: Optional[str] = None,
        drive_dir: str = "drive",
        skip_environment: bool = False,
    ) -> Tuple[str, bool]:
        """
        Return (session_name, was_created).
        Reuses existing running session with matching GPU if available.
        Otherwise creates a new session if auto_create is True.
        """
        gpu = (gpu or "T4").strip().upper()
        existing = self.find_matching_session(gpu, prefer_session=session_name)
        if existing:
            return existing["name"], False

        if not auto_create:
            raise GpuAllocationError(f"No running session with GPU '{gpu}' found, and auto_create is disabled.")

        new_name = session_name or ("colab-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6])
        validate_name(new_name)

        config = SessionConfig(
            cli=self.cli,
            session=new_name,
            gpu=gpu,
            repo_url=repo_url,
            repo_name=repo_name,
            branch=branch,
            drive_dir=drive_dir,
            skip_drive=not mount_drive,
            restore_key=None,
            token=None,
            has_pat_prompt=False,
            has_pat_stdin=False,
            skip_environment=skip_environment,
        )
        try:
            provisioner = SessionProvisioner(config)
            code = provisioner.provision()
            if code != 0:
                raise SessionProvisioningError(f"Failed to create new Colab session '{new_name}' with GPU '{gpu}' (provision exit code {code}).")
        except Exception as exc:
            if isinstance(exc, ColabSessionError):
                raise
            raise SessionProvisioningError(f"Failed to provision Colab session '{new_name}': {exc}") from exc

        return new_name, True
