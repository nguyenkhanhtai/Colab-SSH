"""Manage Colab runtimes and their generated SSH state."""
import json
from pathlib import Path
import re
import shlex
import subprocess

from setup_ssh import alias_for, config_for, reconcile as reconcile_ssh, remove as remove_ssh

SESSION_STATE = Path.home() / '.config/colab-cli/sessions.json'


def validate_name(name):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', name or ''):
        raise ValueError('Invalid session name')
    return name


def read_state(path=None):
    path = SESSION_STATE if path is None else Path(path)
    if not path.exists():
        return {}
    try:
        state = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f'Cannot read Colab session state: {exc}') from exc
    return state if isinstance(state, dict) else {}


def active_names(path=None):
    return {name for name, data in read_state(path).items()
            if isinstance(data, dict) and data.get('running', True)}


def live_names(cli):
    result = subprocess.run([cli, 'sessions'], check=True, capture_output=True, text=True)
    return set(re.findall(r'^\[([^]\n]+)\]', result.stdout, re.MULTILINE))


def reconcile(path=None, cli=None):
    # `colab sessions` can temporarily omit a runtime while an automation such
    # as drivemount owns it. Preserve state-marked runtimes during provisioning.
    active = active_names(path)
    if cli:
        active |= live_names(cli)
    return reconcile_ssh(active)


def sessions(path=None, cli=None):
    state = read_state(path)
    active = {name for name, value in state.items()
              if isinstance(value, dict) and value.get('running', True)}
    if cli:
        active |= live_names(cli)
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


def stop(cli, name):
    validate_name(name)
    try:
        subprocess.run([cli, 'stop', '-s', name], check=True, capture_output=True, text=True)
    finally:
        remove_ssh(name)


def notebook_url(cli, name):
    validate_name(name)
    result = subprocess.run([cli, 'url', '-s', name], check=True,
                            capture_output=True, text=True)
    return result.stdout.strip()
