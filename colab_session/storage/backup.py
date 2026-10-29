"""Backup and restore Colab sessions via Google Drive."""
import json
from pathlib import Path
import re
import secrets
import shlex
import subprocess
from typing import Dict, List, Optional

from colab_session.exceptions import BackupError, DriveNotMountedError
from colab_session.resources import read_resource, render_template
from colab_session.ssh.config import alias_for, config_for
from colab_session.ssh.proxy import command as proxy_command


class BackupKeyManager:
    """Generates and validates unique backup keys (Single Responsibility: Key management)."""

    KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")

    @classmethod
    def generate(cls) -> str:
        """Generate a random unique backup key like 'bk-a1b2c3d4'."""
        return f"bk-{secrets.token_hex(4)}"

    @classmethod
    def validate(cls, key: str) -> str:
        """Validate that the backup key conforms to safe identifier rules."""
        cleaned = str(key or "").strip()
        if not cls.KEY_PATTERN.fullmatch(cleaned):
            raise ValueError("Invalid backup key: use letters, numbers, hyphens, and underscores")
        return cleaned


class BackupScriptGenerator:
    """Generates Python scripts for remote execution on Colab VM (Single Responsibility: Script generation)."""

    @staticmethod
    def backup_script(session_name: str, key: str) -> str:
        return render_template(
            "scripts",
            "remote_backup.py.template",
            context={
                "KEY": key,
                "KEY_REPR": repr(key),
                "SESSION_NAME_REPR": repr(session_name),
            },
        )

    @staticmethod
    def restore_script(key: str) -> str:
        return render_template(
            "scripts",
            "remote_restore.py.template",
            context={
                "KEY": key,
                "KEY_REPR": repr(key),
            },
        )

    @staticmethod
    def list_backups_script() -> str:
        return read_resource("scripts", "remote_list_backups.py")


def ssh_command_for_session(cli: str, session: str, gpu: Optional[str] = None) -> List[str]:
    """Return SSH command line arguments targeting the specified session."""
    proxy = shlex.join(proxy_command(cli, session, gpu=gpu))
    hosts = Path.home() / '.config/colab-ssh/ssh' / f'{session}.known_hosts'
    return [
        "ssh",
        "-F", "/dev/null",
        "-o", f"ProxyCommand={proxy}",
        "-o", f"UserKnownHostsFile={hosts}",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=30",
        f"root@{session}",
    ]


class DriveBackupService:
    """Executes backup and list operations on running Colab sessions."""

    def __init__(self, key_manager: Optional[BackupKeyManager] = None, script_generator: Optional[BackupScriptGenerator] = None):
        self.key_manager = key_manager or BackupKeyManager()
        self.script_generator = script_generator or BackupScriptGenerator()

    def build_ssh_command(self, cli: str, session: str, gpu: Optional[str] = None) -> List[str]:
        return ssh_command_for_session(cli, session, gpu=gpu)

    def backup(self, cli: str, session: str, key: Optional[str] = None) -> Dict:
        """Backup a running session workspace to Google Drive."""
        key = self.key_manager.validate(key or self.key_manager.generate())
        ssh = self.build_ssh_command(cli, session)
        code = self.script_generator.backup_script(session, key)
        try:
            res = subprocess.run(
                [*ssh, "python3 -c " + shlex.quote(code)],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or exc.stdout or str(exc)).strip()
            lines = [ln.strip() for ln in err.splitlines() if ln.strip()]
            last_err = lines[-1] if lines else str(exc)
            if "Google Drive is not mounted" in err:
                raise DriveNotMountedError("Google Drive is not mounted in this session. Mount Drive before backing up.") from exc
            raise BackupError(f"Backup failed on remote VM: {last_err}") from exc

        lines = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
        for line in reversed(lines):
            try:
                data = json.loads(line)
                if data.get("status") == "ok":
                    return data
            except json.JSONDecodeError:
                continue
        raise BackupError(f"Unexpected backup response from remote session: {res.stdout}")

    def list_backups(self, cli: str, session: str) -> List[Dict]:
        """Query available backups from Google Drive via an active session."""
        ssh = self.build_ssh_command(cli, session)
        code = self.script_generator.list_backups_script()
        try:
            res = subprocess.run(
                [*ssh, "python3 -c " + shlex.quote(code)],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or exc.stdout or str(exc)).strip()
            raise BackupError(f"Failed to list backups: {err}") from exc

        lines = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
        for line in reversed(lines):
            try:
                data = json.loads(line)
                if data.get("status") == "ok":
                    return data.get("backups", [])
            except json.JSONDecodeError:
                continue
        return []


_default_service = DriveBackupService()


def generate_key() -> str:
    return BackupKeyManager.generate()


def validate_key(key: str) -> str:
    return BackupKeyManager.validate(key)


def backup_remote_code(session_name: str, key: str) -> str:
    return BackupScriptGenerator.backup_script(session_name, key)


def restore_remote_code(key: str) -> str:
    return BackupScriptGenerator.restore_script(key)


def list_backups_remote_code() -> str:
    return BackupScriptGenerator.list_backups_script()


def backup(cli: str, session: str, key: Optional[str] = None) -> dict:
    return _default_service.backup(cli, session, key=key)


def list_backups(cli: str, session: str) -> list[dict]:
    return _default_service.list_backups(cli, session)

