"""Generate a VS Code Remote-SSH host for a Colab session."""
import argparse
import json
from pathlib import Path
import re
import shlex
import shutil
import time
from ssh_proxy import command as proxy_command

CONFIG_HOME = Path.home() / '.config/colab-ssh'


def alias_for(session):
    return session if session.startswith('colab-') else f'colab-{session}'


def config_for(session):
    return CONFIG_HOME / 'ssh' / f'{session}.conf'


def configure(session, cli, identity=None, gpu=None):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', session):
        raise ValueError('Invalid session name')
    key = Path(identity).expanduser().resolve() if identity else Path.home() / '.ssh/id_ed25519'
    if not key.is_file():
        raise FileNotFoundError(f'SSH key missing: {key}. Create one with ssh-keygen -t ed25519')
    folder = CONFIG_HOME / 'ssh'
    folder.mkdir(parents=True, exist_ok=True)
    alias = alias_for(session)
    hosts = folder / f'{session}.known_hosts'
    # A custom session name may be reused for a different Colab VM. Its host
    # key is therefore valid only for the current configure/create operation.
    hosts.write_text('')
    hosts.chmod(0o600)
    proxy = shlex.join(proxy_command(cli, session, key, gpu))
    entry = (f'Host {alias}\n'
             f'    HostName {session}\n'
             '    User root\n'
             f'    IdentityFile "{key}"\n'
             '    IdentitiesOnly yes\n'
             f'    ProxyCommand {proxy}\n'
             f'    UserKnownHostsFile "{hosts}"\n'
             '    StrictHostKeyChecking accept-new\n'
             '    ServerAliveInterval 30\n'
             '    ServerAliveCountMax 3\n')
    config = config_for(session)
    config.write_text(entry)
    config.chmod(0o600)
    return config, alias


def install(config):
    user_config = Path.home() / '.ssh/config'
    user_config.parent.mkdir(exist_ok=True)
    line = f'Include "{config.parent}/*.conf"'
    legacy = f'Include "{config.parent}/config"'
    text = user_config.read_text() if user_config.exists() else ''
    lines = [item for item in text.splitlines() if item != legacy]
    if line not in lines:
        lines.insert(0, line)
    user_config.write_text('\n'.join(lines).rstrip() + '\n')
    user_config.chmod(0o600)
    try:
        (config.parent / 'config').unlink()
    except FileNotFoundError:
        pass


def remove(session):
    """Remove generated SSH state for one stopped session."""
    removed = []
    paths = [config_for(session), CONFIG_HOME / 'ssh' / f'{session}.known_hosts']
    for path in paths:
        try:
            path.unlink()
            removed.append(path)
        except FileNotFoundError:
            pass
    return removed


def reconcile(active_sessions, grace_seconds=300):
    """Remove stale SSH state, preserving newly provisioned session configs."""
    folder = CONFIG_HOME / 'ssh'
    if not folder.exists():
        return []
    active = set(active_sessions)
    now = time.time()
    stale = {path.stem for path in folder.glob('*.conf')
             if path.stem not in active and now - path.stat().st_mtime >= grace_seconds}
    removed = []
    for session in stale:
        removed.extend(remove(session))
    return removed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', help='Existing session; defaults to the latest colab-* session in local state')
    parser.add_argument('--identity', help='SSH private key path')
    parser.add_argument('--install', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--no-install', action='store_true', help='Generate config only, without registering in ~/.ssh/config')
    args = parser.parse_args()
    session = args.session
    if not session:
        state = Path.home() / '.config/colab-cli/sessions.json'
        sessions = json.loads(state.read_text()) if state.exists() else {}
        candidates = sorted(name for name in sessions if name.startswith('colab-'))
        if not candidates:
            parser.error('No session found. Specify --session NAME')
        session = candidates[-1]
    cli = shutil.which('colab')
    if not cli:
        parser.error('Run with uv run setup_ssh.py')
    try:
        config, alias = configure(session, cli, args.identity)
        if not args.no_install:
            install(config)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print('SSH: ' + shlex.join(['ssh', '-F', str(config), alias]))
    print(f'VS Code: Remote-SSH: Connect to Host → {alias}')
    if args.no_install:
        print('Register with VS Code: uv run setup_ssh.py --session ' + session)


if __name__ == '__main__':
    main()
