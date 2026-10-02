"""Backup and restore Colab sessions via Google Drive."""
import json
from pathlib import Path
import re
import secrets
import shlex
import subprocess

from setup_ssh import alias_for, config_for
from ssh_proxy import command as proxy_command


def generate_key() -> str:
    """Generate a random unique backup key like 'bk-a1b2c3d4'."""
    return f"bk-{secrets.token_hex(4)}"


def validate_key(key: str) -> str:
    """Validate that the backup key conforms to safe identifier rules."""
    key = str(key or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", key):
        raise ValueError("Invalid backup key: use letters, numbers, hyphens, and underscores")
    return key


def backup_remote_code(session_name: str, key: str) -> str:
    """Python code to be executed remotely on the Colab VM to archive workspace to Drive."""
    return f"""import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# 1. Locate Google Drive MyDrive
drive_candidates = list(Path('/content').glob('**/MyDrive'))
if not drive_candidates:
    raise RuntimeError("Google Drive is not mounted in this session. Mount Drive before backing up.")

my_drive = drive_candidates[0]
mount_dir = my_drive.parent

# 2. Determine workspace
if mount_dir.parent not in (Path('/'), Path('/content')):
    workspace = mount_dir.parent
    workspace_name = workspace.name
else:
    workspace = Path('/content')
    workspace_name = ""

# 3. Create backups folder on Google Drive
candidate_dirs = [
    my_drive / 'Colab-Backups',
    my_drive / 'colab-backups',
    my_drive / 'colab_backups',
]
backups_dir = next((p for p in candidate_dirs if p.is_dir()), my_drive / 'Colab-Backups')
backups_dir.mkdir(parents=True, exist_ok=True)

archive_path = backups_dir / f"{key}.tar.gz"
meta_path = backups_dir / f"{key}.json"

# 4. Determine relative path of mount_dir from workspace to exclude from archive
try:
    mount_rel = mount_dir.relative_to(workspace)
    exclude_mount = str(mount_rel)
except ValueError:
    exclude_mount = "drive"

excludes = [
    f"--exclude={{exclude_mount}}",
    "--exclude=.cache",
    "--exclude=__pycache__",
    "--exclude=.ipynb_checkpoints",
    "--exclude=.venv",
    "--exclude=venv",
    "--exclude=*.pyc",
    "--exclude=*.pat",
    "--exclude=auth.json",
    "--exclude=credentials.json",
    "--exclude=.env",
]
if workspace == Path('/content'):
    excludes.extend([
        "--exclude=sample_data",
        "--exclude=.config",
    ])

# 5. Archive workspace into tar.gz
tar_cmd = ["tar", "-czf", str(archive_path), "-C", str(workspace), *excludes, "."]
res = subprocess.run(tar_cmd, capture_output=True, text=True)
if res.returncode != 0:
    raise RuntimeError(f"tar backup failed: {{res.stderr}}")

size_bytes = archive_path.stat().st_size
size_mb = round(size_bytes / (1024 * 1024), 2)

metadata = {{
    "key": {key!r},
    "created_at": datetime.now(timezone.utc).isoformat(),
    "session": {session_name!r},
    "workspace": str(workspace),
    "workspace_name": workspace_name,
    "size_bytes": size_bytes,
    "size_mb": size_mb,
}}
meta_path.write_text(json.dumps(metadata, indent=2))

print(json.dumps({{"status": "ok", "key": {key!r}, "size_mb": size_mb, "path": str(archive_path)}}))
"""


def restore_remote_code(key: str) -> str:
    """Python code to be executed remotely on the Colab VM to extract backup archive from Drive."""
    return f"""import json
import os
import subprocess
from pathlib import Path

# 1. Locate Google Drive MyDrive
drive_candidates = list(Path('/content').glob('**/MyDrive'))
if not drive_candidates:
    raise RuntimeError("Google Drive is not mounted. Cannot access backup.")

my_drive = drive_candidates[0]
candidate_dirs = [
    my_drive / 'Colab-Backups',
    my_drive / 'colab-backups',
    my_drive / 'colab_backups',
]
backups_dir = next((p for p in candidate_dirs if (p / f"{key}.tar.gz").is_file()), my_drive / 'Colab-Backups')
archive_path = backups_dir / f"{key}.tar.gz"
meta_path = backups_dir / f"{key}.json"

if not archive_path.is_file():
    raise RuntimeError(f"Backup key '{key}' not found in Google Drive ({{archive_path}}).")

workspace_name = ""
if meta_path.is_file():
    try:
        meta = json.loads(meta_path.read_text())
        workspace_name = meta.get("workspace_name", "")
    except Exception:
        pass

if workspace_name:
    workspace = Path('/content') / workspace_name
    workspace.mkdir(parents=True, exist_ok=True)
    tar_cmd = ["tar", "--no-same-owner", "-xzf", str(archive_path), "-C", str(workspace)]
    res = subprocess.run(tar_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"tar restore failed: {{res.stderr}}")
    mount_link = workspace / 'drive'
    if not mount_link.exists() and not mount_link.is_symlink():
        mount_dir = my_drive.parent
        mount_link.symlink_to(mount_dir)
else:
    workspace = Path('/content')
    tar_cmd = ["tar", "--no-same-owner", "--exclude=drive", "-xzf", str(archive_path), "-C", str(workspace)]
    res = subprocess.run(tar_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"tar restore failed: {{res.stderr}}")

print(json.dumps({{"status": "ok", "key": {key!r}, "workspace": str(workspace)}}))
"""


def list_backups_remote_code() -> str:
    """Python code to query all backup records stored in Google Drive."""
    return """import json
from pathlib import Path

drive_candidates = list(Path('/content').glob('**/MyDrive'))
if not drive_candidates:
    raise RuntimeError("Google Drive is not mounted in this session.")

my_drive = drive_candidates[0]
candidate_dirs = [
    my_drive / 'Colab-Backups',
    my_drive / 'colab-backups',
    my_drive / 'colab_backups',
]
items = []
seen_keys = set()
for backups_dir in candidate_dirs:
    if backups_dir.is_dir():
        for meta_file in sorted(backups_dir.glob('*.json'), reverse=True):
            try:
                data = json.loads(meta_file.read_text())
                k = data.get('key')
                if k and k not in seen_keys:
                    seen_keys.add(k)
                    items.append(data)
            except Exception:
                pass

print(json.dumps({"status": "ok", "backups": items}))
"""


def ssh_command_for_session(cli: str, session: str, gpu: str = None) -> list[str]:
    """Return SSH command line arguments targeting the specified session."""
    config = config_for(session)
    if config.is_file():
        return ["ssh", "-F", str(config), alias_for(session)]
    proxy = shlex.join(proxy_command(cli, session, gpu=gpu))
    hosts = Path.home() / '.config/colab-ssh/ssh' / f'{session}.known_hosts'
    return [
        "ssh",
        "-o", f"ProxyCommand={proxy}",
        "-o", f"UserKnownHostsFile={hosts}",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=30",
        f"root@{session}",
    ]


def backup(cli: str, session: str, key: str = None) -> dict:
    """Backup a running session workspace to Google Drive."""
    key = validate_key(key or generate_key())
    ssh = ssh_command_for_session(cli, session)
    code = backup_remote_code(session, key)
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
            raise RuntimeError("Google Drive is not mounted in this session. Mount Drive before backing up.") from exc
        raise RuntimeError(f"Backup failed on remote VM: {last_err}") from exc

    lines = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
    for line in reversed(lines):
        try:
            data = json.loads(line)
            if data.get("status") == "ok":
                return data
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"Unexpected backup response from remote session: {res.stdout}")


def list_backups(cli: str, session: str) -> list[dict]:
    """Query available backups from Google Drive via an active session."""
    ssh = ssh_command_for_session(cli, session)
    code = list_backups_remote_code()
    try:
        res = subprocess.run(
            [*ssh, "python3 -c " + shlex.quote(code)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"Failed to list backups: {err}") from exc

    lines = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
    for line in reversed(lines):
        try:
            data = json.loads(line)
            if data.get("status") == "ok":
                return data.get("backups", [])
        except json.JSONDecodeError:
            continue
    return []

