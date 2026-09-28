#!/usr/bin/env python3
"""Create a Colab session, clone a GitHub repository, and mount Drive inside it."""

import argparse
from datetime import datetime, timezone
import getpass
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import warnings
from uuid import uuid4


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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=github_url, help="GitHub HTTPS repository URL")
    parser.add_argument("--gpu", default="T4")
    parser.add_argument("--session", help="Name for a NEW session")
    parser.add_argument("--branch", help="Branch or tag to clone")
    parser.add_argument("--drive-dir", default="drive", help="Mount directory inside the repo")
    parser.add_argument("--pat", action="store_true", help="Prompt for a GitHub PAT (hidden input); otherwise use GH_TOKEN if set")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", args.drive_dir):
        parser.error("--drive-dir must be a simple directory name, e.g. drive or data")
    url, name = args.repo
    session = args.session or ("colab-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6])
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", session):
        parser.error("Invalid session name: use letters, numbers, hyphens and underscores")
    cli = shutil.which("colab")
    if cli is None:
        parser.error("Colab CLI missing. Run: uv run start_colab.py <github-url>")
    token = os.environ.get("GH_TOKEN", "")
    if args.pat:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                token = getpass.getpass("GitHub PAT (hidden): ").strip()
        except (getpass.GetPassWarning, EOFError):
            parser.error("Hidden input requires a terminal. For automation, set GH_TOKEN.")
        except KeyboardInterrupt:
            return 1
        if not token:
            parser.error("PAT cannot be empty")
    if token and not shutil.which("ssh"):
        parser.error("OpenSSH is required to transfer the PAT securely to the VM")
    remote = f"/content/{name}"
    stop = shlex.join([cli, "stop", "-s", session])
    print(f"Creating {session} ({args.gpu})", flush=True)
    try:
        subprocess.run([cli, "new", "-s", session, "--gpu", args.gpu], check=True)
        print(f"Session: {session}\nStop when finished: {stop}", flush=True)
        if token:
            # colab exec records code in history: send secrets only over SSH stdin.
            proxy = shlex.join([cli, "ssh", "--proxy-mode", "-s", session])
            code = clone_code(url, remote, args.branch, args.drive_dir, authenticated=True)
            subprocess.run(["ssh", "-o", f"ProxyCommand={proxy}",
                            "-o", "StrictHostKeyChecking=accept-new",
                            "-o", "ConnectTimeout=30", f"root@{session}",
                            "python3 -c " + shlex.quote(code)],
                           input=json.dumps(token), text=True, check=True)
            token = None
        else:
            subprocess.run([cli, "exec", "-s", session, "--timeout", "600"],
                           input=clone_code(url, remote, args.branch, args.drive_dir), text=True, check=True)
        subprocess.run([cli, "drivemount", "-s", session, f"{remote}/{args.drive_dir}"], check=True)
        subprocess.run([cli, "exec", "-s", session], input=(
            f"from pathlib import Path\n"
            f"assert Path({(remote + '/' + args.drive_dir + '/MyDrive')!r}).is_dir(), 'Drive mount failed'\n"
        ), text=True, check=True)
    except (subprocess.CalledProcessError, KeyboardInterrupt):
        print(f"Setup interrupted or failed. Session {session} may still be active.\n"
              f"Inspect: {shlex.join([cli, 'status', '-s', session])}\nStop: {stop}", file=sys.stderr)
        return 1
    print(f"READY: {remote}\nDrive: {remote}/{args.drive_dir}/MyDrive")
    print("Connect: " + shlex.join([cli, "ssh", "-s", session]))
    print("Browser: " + shlex.join([cli, "url", "-s", session]))
    print(f"Stop: {stop}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
