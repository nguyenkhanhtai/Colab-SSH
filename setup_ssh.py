"""Generate a VS Code Remote-SSH host for a Colab session."""
import argparse
import json
from pathlib import Path
import re
import shlex
import shutil
from ssh_proxy import command as proxy_command

ROOT = Path(__file__).resolve().parent


def configure(session, cli, identity=None, gpu=None):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', session):
        raise ValueError('Invalid session name')
    key = Path(identity).expanduser().resolve() if identity else Path.home() / '.ssh/id_ed25519'
    if not key.is_file():
        raise FileNotFoundError(f'SSH key missing: {key}. Create one with ssh-keygen -t ed25519')
    folder = ROOT / '.ssh'
    folder.mkdir(exist_ok=True)
    alias = 'colab-session'
    hosts = folder / f'{session}.known_hosts'
    hosts.touch(exist_ok=True)
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
    config = folder / 'config'
    # Generated config represents the current VM; host keys remain per session.
    config.write_text(entry)
    config.chmod(0o600)
    return config, alias


def install(config):
    user_config = Path.home() / '.ssh/config'
    user_config.parent.mkdir(exist_ok=True)
    line = f'Include "{config}"'
    text = user_config.read_text() if user_config.exists() else ''
    if line not in text.splitlines():
        user_config.write_text(line + '\n\n' + text)
        user_config.chmod(0o600)


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
