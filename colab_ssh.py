#!/usr/bin/env python3
"""Create a Colab session, optionally clone GitHub, and mount Google Drive."""

import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import warnings
from uuid import uuid4
from setup_ssh import configure, install
from setup_environment import load_profile, register_extensions, apply as apply_environment
from ssh_proxy import command as proxy_command
from credentials import DEFAULT_AUTH, read_auth, read_pat
from setup_gpu import remote_code as gpu_setup_code


def github_url(value):
    match = re.fullmatch(r"https://github\.com/([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?", value)
    if not match or match[2] in {".", ".."}:
        raise argparse.ArgumentTypeError("Use https://github.com/OWNER/REPO (without credentials)")
    return f"https://github.com/{match[1]}/{match[2]}.git", match[2]


def clone_code(url, remote, branch, drive_dir, authenticated=False):
    command = ["git", "clone"]
    if branch:
        command += ["--branch", branch]
    command += ["--", url, remote]
    clone = f'subprocess.run({command!r}, check=True, env={{**os.environ, "GIT_TERMINAL_PROMPT": "0"}})'
    if authenticated:
        clone = f'''import json
import sys
import tempfile
token = json.load(sys.stdin)
with tempfile.TemporaryDirectory(prefix="colab-git-") as tmp:
    askpass = Path(tmp) / "askpass.py"
    askpass.write_text("#!/usr/bin/env python3\\nimport os, sys\\nprint('x-access-token' if 'username' in sys.argv[1].lower() else os.environ['COLAB_GIT_TOKEN'])\\n")
    askpass.chmod(0o700)
    env = {{**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": str(askpass), "COLAB_GIT_TOKEN": token}}
    try:
        subprocess.run({[command[0], '-c', 'credential.helper=', *command[1:]]!r}, check=True, env=env)
    finally:
        env.pop("COLAB_GIT_TOKEN", None)
        del token
'''
    return f'''import os
import subprocess
from pathlib import Path
repo = Path({remote!r})
{clone}
mount = repo / {drive_dir!r}
if mount.exists() or mount.is_symlink():
    raise RuntimeError(f"Drive path already exists: {{mount}}; choose another --drive-dir")
mount.mkdir()
with (repo / '.git/info/exclude').open('a') as f:
    f.write({chr(10) + '/' + drive_dir + '/' + chr(10)!r})
os.chdir(repo)
'''


def prepare_workspace_code(remote, drive_dir):
    return f'''from pathlib import Path
workspace = Path({remote!r})
workspace.mkdir(parents=True, exist_ok=True)
mount = workspace / {drive_dir!r}
if mount.exists() or mount.is_symlink():
    raise RuntimeError(f"Drive path already exists: {{mount}}; choose another --drive-dir")
mount.mkdir()
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", type=github_url,
                        help="Optional GitHub HTTPS repository URL")
    parser.add_argument("--gpu", default="T4")
    parser.add_argument("--session", help="Name for a NEW session")
    parser.add_argument("--branch", help="Branch or tag to clone")
    parser.add_argument("--drive-dir", default="drive", help="Mount directory inside the workspace")
    args = parser.parse_args(argv)
    if args.branch and not args.repo:
        parser.error("--branch requires a GitHub repository URL")
    if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", args.drive_dir):
        parser.error("--drive-dir must be a simple directory name, e.g. drive or data")
    session = args.session or ("colab-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6])
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", session):
        parser.error("Invalid session name: use letters, numbers, hyphens and underscores")
    cli = shutil.which("colab")
    if cli is None:
        parser.error("Colab CLI missing. Run: uv run colab_ssh.py [github-url]")
    if args.repo:
        url, name = args.repo
        remote = f"/content/{name}"
        setup_code = clone_code(url, remote, args.branch, args.drive_dir)
    else:
        remote = "/content"
        setup_code = prepare_workspace_code(remote, args.drive_dir)
    stop = shlex.join([cli, "stop", "-s", session])
    print(f"Creating {session} ({args.gpu})", flush=True)
    try:
        subprocess.run([cli, "new", "-s", session, "--gpu", args.gpu], check=True)
        print(f"Session: {session}\nStop when finished: {stop}", flush=True)
        subprocess.run([cli, "exec", "-s", session, "--timeout", "600"],
                       input=setup_code, text=True, check=True)
        subprocess.run([cli, "drivemount", "-s", session, f"{remote}/{args.drive_dir}"], check=True)
        verify = (
            f"from pathlib import Path\n"
            f"assert Path({(remote + '/.git')!r}).is_dir(), 'Repository clone missing'\n"
            f"assert Path({(remote + '/' + args.drive_dir + '/MyDrive')!r}).is_dir(), 'Drive mount failed'\n"
        )
        subprocess.run([*ssh, "python3 -c " + shlex.quote(verify)], check=True)
    except (subprocess.CalledProcessError, KeyboardInterrupt):
        print(f"Setup interrupted or failed. Session {session} may still be active.\n"
              f"Inspect: {shlex.join([cli, 'status', '-s', session])}\nStop: {stop}", file=sys.stderr)
        return 1
    print(f"READY: {remote}\nDrive: {remote}/{args.drive_dir}/MyDrive")
    print("Connect: " + shlex.join(ssh))
    print("Browser: " + shlex.join([cli, "url", "-s", session]))
    print(f"Stop: {stop}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
