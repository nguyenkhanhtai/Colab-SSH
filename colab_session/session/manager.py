"""Manage Colab runtimes and their generated SSH state."""
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Set

from colab_session.ssh.config import alias_for, config_for, reconcile as reconcile_ssh, remove as remove_ssh

SESSION_STATE = Path.home() / '.config/colab-cli/sessions.json'


class SessionStateStore:
    """Reads and parses session state JSON records (Single Responsibility: State storage)."""

    def __init__(self, default_path: Optional[Path] = None):
        self.default_path = default_path or SESSION_STATE

    def read_state(self, path: Optional[Path | str] = None) -> Dict[str, Any]:
        target = self.default_path if path is None else Path(path)
        if not target.exists():
            return {}
        try:
            state = json.loads(target.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f'Cannot read Colab session state: {exc}') from exc
        return state if isinstance(state, dict) else {}

    def active_names(self, path: Optional[Path | str] = None) -> Set[str]:
        return {name for name, data in self.read_state(path).items()
                if isinstance(data, dict) and data.get('running', True)}


class ColabCliFinder:
    """Discovers and patches the local colab CLI executable."""

    @staticmethod
    def patch_colab_cli() -> None:
        try:
            import colab_cli.commands.automation as auto
            target = Path(auto.__file__)
            text = target.read_text(encoding="utf-8")
            broken = 'with open("/dev/tty") as tty:\n                    tty.readline()'
            fixed = ('try:\n'
                     '                    with open("/dev/tty") as tty:\n'
                     '                        tty.readline()\n'
                     '                except Exception:\n'
                     '                    sys.stdin.readline()')
            if broken in text:
                target.write_text(text.replace(broken, fixed), encoding="utf-8")
        except Exception:
            pass

    @classmethod
    def find_colab_cli(cls) -> Optional[str]:
        cls.patch_colab_cli()
        cli = shutil.which("colab")
        if cli:
            return cli
        bundled = Path(sys.executable).parent / "colab"
        return str(bundled) if bundled.is_file() else None


def patch_colab_cli() -> None:
    ColabCliFinder.patch_colab_cli()


def find_colab_cli() -> Optional[str]:
    return ColabCliFinder.find_colab_cli()


class ColabCliClient:
    """Wrapper around colab CLI commands (Single Responsibility: External CLI execution)."""

    @staticmethod
    def live_names(cli: str) -> Set[str]:
        result = subprocess.run([cli, 'sessions'], check=True, capture_output=True, text=True)
        return set(re.findall(r'^\[([^]\n]+)\]', result.stdout, re.MULTILINE))

    @staticmethod
    def stop_session(cli: str, name: str) -> None:
        subprocess.run([cli, 'stop', '-s', name], check=True, capture_output=True, text=True)

    @staticmethod
    def notebook_url(cli: str, name: str) -> str:
        result = subprocess.run([cli, 'url', '-s', name], check=True,
                                capture_output=True, text=True)
        return result.stdout.strip()


class SessionManager:
    """Coordinates session queries, lifecycle, and SSH state reconciliation."""

    NAME_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]*')

    def __init__(self, state_store: Optional[SessionStateStore] = None, cli_client: Optional[ColabCliClient] = None):
        self.state_store = state_store or SessionStateStore()
        self.cli_client = cli_client or ColabCliClient()

    @classmethod
    def validate_name(cls, name: str) -> str:
        if not cls.NAME_PATTERN.fullmatch(name or ''):
            raise ValueError('Invalid session name')
        return name

    def active_names(self, path: Optional[Path | str] = None) -> Set[str]:
        return self.state_store.active_names(path)

    def live_names(self, cli: str) -> Set[str]:
        return self.cli_client.live_names(cli)

    def reconcile(self, path: Optional[Path | str] = None, cli: Optional[str] = None) -> List[Path]:
        active = self.active_names(path)
        if cli:
            active |= self.cli_client.live_names(cli)
        return reconcile_ssh(active)

    def get_sessions(self, path: Optional[Path | str] = None, cli: Optional[str] = None) -> List[Dict[str, Any]]:
        state = self.state_store.read_state(path)
        active = {name for name, value in state.items()
                  if isinstance(value, dict) and value.get('running', True)}
        if cli:
            active |= self.cli_client.live_names(cli)
        reconcile_ssh(active)
        result = []
        for name, value in sorted(state.items()):
            if name not in active or not isinstance(value, dict):
                continue
            result.append({
                'name': name,
                'gpu': value.get('accelerator') or value.get('variant') or 'unknown',
                'shape': value.get('machine_shape') or 'unknown',
                'running': True,
                'ssh_alias': alias_for(name),
                'ssh_command': shlex.join(['ssh', alias_for(name)]),
                'ssh_configured': config_for(name).is_file(),
                'last_execution': value.get('last_execution'),
            })
        return result

    def stop(self, cli: str, name: str) -> None:
        self.validate_name(name)
        try:
            subprocess.run([cli, 'stop', '-s', name], check=True, capture_output=True, text=True)
        finally:
            remove_ssh(name)

    def notebook_url(self, cli: str, name: str) -> str:
        self.validate_name(name)
        result = subprocess.run([cli, 'url', '-s', name], check=True,
                                capture_output=True, text=True)
        return result.stdout.strip()


_default_manager = SessionManager()


def validate_name(name: str) -> str:
    return SessionManager.validate_name(name)


def read_state(path: Optional[Path | str] = None) -> Dict[str, Any]:
    return _default_manager.state_store.read_state(path)


def active_names(path: Optional[Path | str] = None) -> Set[str]:
    return _default_manager.state_store.active_names(path)


def live_names(cli: str) -> Set[str]:
    return ColabCliClient.live_names(cli)


def reconcile(path: Optional[Path | str] = None, cli: Optional[str] = None) -> List[Path]:
    return _default_manager.reconcile(path, cli)


def sessions(path: Optional[Path | str] = None, cli: Optional[str] = None) -> List[Dict[str, Any]]:
    return _default_manager.get_sessions(path, cli)


def stop(cli: str, name: str) -> None:
    _default_manager.stop(cli, name)


def notebook_url(cli: str, name: str) -> str:
    return _default_manager.notebook_url(cli, name)

