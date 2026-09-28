"""Connect only to an existing GPU session; never silently create a CPU VM."""
import argparse
import json
import os
from pathlib import Path
import sys


def validate(session, gpu=None):
    path = Path.home() / '.config/colab-cli/sessions.json'
    state = json.loads(path.read_text()) if path.exists() else {}
    current = state.get(session)
    if not current:
        raise ValueError(f'Session {session} has stopped or is missing. Create a new session with start_colab.py.')
    if current.get('variant') != 'GPU' or current.get('accelerator') in (None, 'NONE'):
        raise ValueError(f'Session {session} is a CPU runtime. Create a new GPU session with start_colab.py.')
    if gpu and current.get('accelerator', '').upper() != gpu.upper():
        raise ValueError(f'Session GPU is {current.get("accelerator")}, expected {gpu}.')


def command(cli, session, identity=None, gpu=None):
    result = [sys.executable, str(Path(__file__).resolve()), '--cli', str(cli), '--session', session]
    if identity:
        result += ['--identity', str(identity)]
    if gpu:
        result += ['--gpu', gpu]
    return result


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
    # Explicit accelerator also prevents CPU creation if the session is removed
    # in the narrow gap between the state check and the CLI reading its state.
    state = json.loads((Path.home() / '.config/colab-cli/sessions.json').read_text())
    cmd += ['--gpu', args.gpu or state[args.session]['accelerator']]
    if args.identity:
        cmd += ['--identity', args.identity]
    os.execv(args.cli, cmd)


if __name__ == '__main__':
    sys.exit(main())
