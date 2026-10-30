"""Connect only to an existing GPU session; never silently create a CPU VM."""
import argparse
import json
import os
from pathlib import Path
import sys
from typing import List, Optional


class SessionProxyValidator:
    """Validates session status and accelerator type before proxying SSH connections."""

    @staticmethod
    def validate(session: str, gpu: Optional[str] = None) -> None:
        path = Path.home() / '.config/colab-cli/sessions.json'
        state = json.loads(path.read_text()) if path.exists() else {}
        current = state.get(session)
        if not current:
            raise ValueError(f'Session {session} has stopped or is missing. Create a new session with colab_ssh.py.')
        if current.get('variant') != 'GPU' or current.get('accelerator') in (None, 'NONE'):
            raise ValueError(f'Session {session} is a CPU runtime. Create a new GPU session with colab_ssh.py.')
        if gpu and current.get('accelerator', '').upper() != gpu.upper():
            raise ValueError(f'Session GPU is {current.get("accelerator")}, expected {gpu}.')


class SSHProxyCommandBuilder:
    """Builds proxycommand argument arrays."""

    @staticmethod
    def command(cli: str, session: str, identity: Optional[Path | str] = None, gpu: Optional[str] = None, script_path: Optional[str] = None) -> List[str]:
        target_script = script_path or str(Path(__file__).resolve())
        result = [sys.executable, target_script, '--cli', str(cli), '--session', session]
        if identity:
            result += ['--identity', str(identity)]
        if gpu:
            result += ['--gpu', gpu]
        return result


def validate(session: str, gpu: Optional[str] = None) -> None:
    SessionProxyValidator.validate(session, gpu)


def command(cli: str, session: str, identity: Optional[Path | str] = None, gpu: Optional[str] = None) -> List[str]:
    # Check if root ssh_proxy.py exists to maintain proxy execution path
    root_proxy = Path(__file__).parent.parent.parent / 'ssh_proxy.py'
    target = str(root_proxy.resolve()) if root_proxy.is_file() else str(Path(__file__).resolve())
    return SSHProxyCommandBuilder.command(cli, session, identity, gpu, script_path=target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--identity')
    parser.add_argument('--gpu')
    args = parser.parse_args()
    try:
        validate(args.session, args.gpu)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    cmd = [args.cli, 'ssh', '--proxy-mode', '-s', args.session]
    if args.identity:
        cmd += ['--identity', args.identity]
    os.execv(args.cli, cmd)


if __name__ == '__main__':
    sys.exit(main())

