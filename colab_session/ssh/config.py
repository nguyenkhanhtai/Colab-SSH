"""Generate a VS Code Remote-SSH host for a Colab session."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import time
from typing import List, Optional, Tuple

from colab_session.ssh.proxy import command as proxy_command

CONFIG_HOME = Path.home() / '.config/colab-ssh'


class SSHNaming:
    """Naming conventions for Colab SSH hosts and aliases (Single Responsibility)."""

    NAME_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]*')

    @classmethod
    def validate(cls, name: str) -> str:
        if not cls.NAME_PATTERN.fullmatch(name or ''):
            raise ValueError('Invalid session name')
        return name

    @classmethod
    def alias(cls, session: str) -> str:
        return session if session.startswith('colab-') else f'colab-{session}'


class SSHConfigManager:
    """Manages SSH configuration files, known_hosts, and user ~/.ssh/config integration."""

    def __init__(self, config_home: Optional[Path] = None):
        self._config_home = config_home

    @property
    def config_home(self) -> Path:
        return self._config_home if self._config_home is not None else CONFIG_HOME

    @property
    def ssh_dir(self) -> Path:
        return self.config_home / 'ssh'

    def alias_for(self, session: str) -> str:
        return SSHNaming.alias(session)

    def config_for(self, session: str) -> Path:
        return self.ssh_dir / f'{session}.conf'

    def known_hosts_for(self, session: str) -> Path:
        return self.ssh_dir / f'{session}.known_hosts'

    def configure(self, session: str, cli: str, identity: Optional[str | Path] = None, gpu: Optional[str] = None) -> Tuple[Path, str]:
        SSHNaming.validate(session)
        key = Path(identity).expanduser().resolve() if identity else Path.home() / '.ssh/id_ed25519'
        if not key.is_file():
            raise FileNotFoundError(f'SSH key missing: {key}. Create one with ssh-keygen -t ed25519')
        self.ssh_dir.mkdir(parents=True, exist_ok=True)
        alias = self.alias_for(session)
        hosts = self.known_hosts_for(session)
        hosts.write_text('')
        hosts.chmod(0o600)
        proxy_cmd = proxy_command(cli, session, key, gpu)
        in_docker = Path('/.dockerenv').exists()
        if in_docker:
            container = os.environ.get('COLAB_SSH_CONTAINER', 'colab-ssh-dashboard')
            proxy = shlex.join(['docker', 'exec', '-i', container, *proxy_cmd])
            key_str = f'~/.ssh/{key.name}' if key.parent == Path.home() / '.ssh' else str(key)
            hosts_str = f'~/.config/colab-ssh/ssh/{session}.known_hosts'
        else:
            proxy = shlex.join(proxy_cmd)
            key_str = str(key)
            hosts_str = str(hosts)
        entry = (f'Host {alias}\n'
                 f'    HostName {session}\n'
                 '    User root\n'
                 f'    IdentityFile "{key_str}"\n'
                 '    IdentitiesOnly yes\n'
                 f'    ProxyCommand {proxy}\n'
                 f'    UserKnownHostsFile "{hosts_str}"\n'
                 '    StrictHostKeyChecking accept-new\n'
                 '    ServerAliveInterval 30\n'
                 '    ServerAliveCountMax 3\n')
        config = self.config_for(session)
        config.write_text(entry)
        config.chmod(0o600)
        if in_docker and hasattr(os, 'chown'):
            st = self.ssh_dir.stat()
            for path in (hosts, config):
                try:
                    os.chown(path, st.st_uid, st.st_gid)
                except OSError:
                    pass
        return config, alias

    def install(self, config: Path) -> None:
        user_config = Path.home() / '.ssh/config'
        user_config.parent.mkdir(exist_ok=True)
        in_docker = Path('/.dockerenv').exists()
        line = 'Include "~/.config/colab-ssh/ssh/*.conf"' if in_docker else f'Include "{config.parent}/*.conf"'
        legacy = f'Include "{config.parent}/config"'
        text = user_config.read_text() if user_config.exists() else ''
        lines = [item for item in text.splitlines()
                 if item not in (legacy, 'Include "/root/.config/colab-ssh/ssh/*.conf"')]
        if line not in lines and f'Include "{config.parent}/*.conf"' not in lines:
            lines.insert(0, line)
        user_config.write_text('\n'.join(lines).rstrip() + '\n')
        user_config.chmod(0o600)
        if in_docker and hasattr(os, 'chown'):
            st = user_config.parent.stat()
            try:
                os.chown(user_config, st.st_uid, st.st_gid)
            except OSError:
                pass
        try:
            (config.parent / 'config').unlink()
        except FileNotFoundError:
            pass

    def remove(self, session: str) -> List[Path]:
        """Remove generated SSH state for one stopped session."""
        removed = []
        paths = [self.config_for(session), self.known_hosts_for(session)]
        for path in paths:
            try:
                path.unlink()
                removed.append(path)
            except FileNotFoundError:
                pass
        return removed

    def reconcile(self, active_sessions, grace_seconds: int = 300) -> List[Path]:
        """Remove stale SSH state, preserving newly provisioned session configs."""
        if not self.ssh_dir.exists():
            return []
        active = set(active_sessions)
        now = time.time()
        stale = {path.stem for path in self.ssh_dir.glob('*.conf')
                 if path.stem not in active and now - path.stat().st_mtime >= grace_seconds}
        removed = []
        for session in stale:
            removed.extend(self.remove(session))
        return removed


_default_manager = SSHConfigManager()


def alias_for(session: str) -> str:
    return _default_manager.alias_for(session)


def config_for(session: str) -> Path:
    return _default_manager.config_for(session)


def configure(session: str, cli: str, identity: Optional[str | Path] = None, gpu: Optional[str] = None) -> Tuple[Path, str]:
    return _default_manager.configure(session, cli, identity=identity, gpu=gpu)


def install(config: Path) -> None:
    _default_manager.install(config)


def remove(session: str) -> List[Path]:
    return _default_manager.remove(session)


def reconcile(active_sessions, grace_seconds: int = 300) -> List[Path]:
    return _default_manager.reconcile(active_sessions, grace_seconds=grace_seconds)

