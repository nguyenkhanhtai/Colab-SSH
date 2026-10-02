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
from setup_environment import load_profile, register_extensions, apply as apply_environment, sync_context
from ssh_proxy import command as proxy_command
from credentials import DEFAULT_AUTH, read_auth, read_pat, save_pat_mapping
from setup_gpu import remote_code as gpu_setup_code
import backup_manager


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


def patch_colab_cli():
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


def find_colab_cli():
    patch_colab_cli()
    cli = shutil.which("colab")
    if cli:
        return cli
    # uv tool keeps dependency executables beside its Python, outside caller PATH.
    bundled = Path(sys.executable).parent / "colab"
    return str(bundled) if bundled.is_file() else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", type=github_url, help="Optional GitHub HTTPS repository URL")
    parser.add_argument("--gpu", default="T4", type=str.upper, choices=['T4', 'L4', 'G4', 'A100', 'H100'])
    parser.add_argument("--session", help="Name for a NEW session")
    parser.add_argument("--branch", help="Branch or tag to clone")
    parser.add_argument("--drive-dir", default="drive", help="Mount directory inside the workspace")
    parser.add_argument("--skip-drive", action="store_true", help="Do not mount Google Drive")
    auth = parser.add_mutually_exclusive_group()
    auth.add_argument("--pat", action="store_true", help="Prompt for a GitHub PAT (hidden input)")
    auth.add_argument("--pat-stdin", action="store_true", help=argparse.SUPPRESS)
    auth.add_argument("--pat-file", type=Path, help="Read a GitHub PAT from a local text file")
    auth.add_argument("--auth-file", type=Path, help="JSON config containing credential file paths")
    parser.add_argument("--skip-environment", action="store_true", help="Skip CLI installation and VS Code profile")
    management = parser.add_mutually_exclusive_group()
    management.add_argument("--list", action="store_true", help="List active sessions")
    management.add_argument("--stop", metavar="SESSION", help="Stop a session and remove its SSH state")
    management.add_argument("--serve", action="store_true", help="Run the local multi-session dashboard")
    management.add_argument("--backup", metavar="SESSION", help="Backup a running session workspace to Google Drive")
    management.add_argument("--list-backups", action="store_true", help="List available backups on Google Drive")
    parser.add_argument("--restore", metavar="KEY", help="Restore workspace from a Google Drive backup key in a NEW session")
    parser.add_argument("--host", default=os.environ.get("COLAB_SSH_HOST", "127.0.0.1"), help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=int(os.environ.get("COLAB_SSH_PORT", "6767")), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.list or args.stop or args.serve or args.backup or args.list_backups:
        if args.repo:
            parser.error("A repository URL cannot be combined with management commands")
        if args.restore:
            parser.error("--restore cannot be combined with management commands")
        cli = find_colab_cli()
        if cli is None:
            parser.error("Colab CLI missing. Install with: uv tool install -e .")
        if args.serve:
            from colab_server import serve
            serve(args.host, args.port)
            return 0
        import session_manager
        if args.backup:
            try:
                session_manager.validate_name(args.backup)
                print(f"Backing up session '{args.backup}' to Google Drive...", flush=True)
                res = backup_manager.backup(cli, args.backup)
            except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
                parser.error(str(exc))
            print(f"Backup successful!\n"
                  f"Backup Key: {res['key']}\n"
                  f"Size: {res.get('size_mb', 'N/A')} MB\n"
                  f"Path: {res.get('path')}\n"
                  f"To restore in a new session: colab-ssh --restore {res['key']}")
            return 0
        if args.list_backups:
            rows = session_manager.sessions(cli=cli)
            if not rows:
                parser.error("No active session found to read Google Drive backups. At least one running session is required.")
            try:
                backups = backup_manager.list_backups(cli, rows[0]['name'])
            except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
                parser.error(str(exc))
            if not backups:
                print("No backups found in Google Drive (MyDrive/Colab-Backups)")
            else:
                print(f"{'KEY':<16} {'CREATED (UTC)':<24} {'SESSION':<20} {'SIZE':<10} {'WORKSPACE'}")
                print("-" * 85)
                for b in backups:
                    print(f"{b.get('key', ''):<16} {str(b.get('created_at', ''))[:19]:<24} {b.get('session', ''):<20} {str(b.get('size_mb', '')) + ' MB':<10} {b.get('workspace', '')}")
            return 0
        if args.stop:
            try:
                session_manager.stop(cli, args.stop)
            except (ValueError, OSError, subprocess.CalledProcessError) as exc:
                parser.error(str(exc))
            print(f"Stopped {args.stop} and removed its SSH state")
            return 0
        rows = session_manager.sessions(cli=cli)
        if not rows:
            print("No active Colab sessions")
        for item in rows:
            print(f"{item['name']}  {item['gpu']}  {item['ssh_command']}")
        return 0
    if args.restore:
        if args.repo:
            parser.error("A repository URL cannot be combined with --restore")
        if args.branch:
            parser.error("--branch cannot be combined with --restore")
        if args.skip_drive:
            parser.error("--skip-drive cannot be combined with --restore (Drive is required to access backups)")
        try:
            backup_manager.validate_key(args.restore)
        except ValueError as exc:
            parser.error(str(exc))
    if args.branch and not args.repo:
        parser.error("--branch requires a GitHub repository URL")
    if not args.repo and (args.pat or args.pat_stdin or args.pat_file or args.auth_file):
        parser.error("PAT options require a GitHub repository URL")
    if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", args.drive_dir):
        parser.error("--drive-dir must be a simple directory name, e.g. drive or data")
    url, name = args.repo if args.repo else (None, None)
    session = args.session or ("colab-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6])
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", session):
        parser.error("Invalid session name: use letters, numbers, hyphens and underscores")
    cli = find_colab_cli()
    if cli is None:
        parser.error("Colab CLI missing. Install with: uv tool install -e .")
    token = os.environ.get("GH_TOKEN", "") if args.repo else ""
    try:
        if args.pat_stdin:
            token = sys.stdin.readline().strip()
            if not token:
                parser.error("PAT from stdin cannot be empty")
        elif args.pat_file:
            token = read_pat(args.pat_file)
        elif args.auth_file:
            token = read_auth(args.auth_file, repo_url=url)
            if not token:
                parser.error('Auth config has no PAT for this repository')
        elif args.repo and not args.pat and not args.pat_stdin and DEFAULT_AUTH.is_file():
            token = read_auth(DEFAULT_AUTH, repo_url=url) or token
    except ValueError as exc:
        parser.error(str(exc))
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
    if not shutil.which("ssh"):
        parser.error("OpenSSH is required to prepare and verify the VM")
    remote = f"/content/{name}" if args.repo else "/content"
    profile = None
    if not args.skip_environment:
        profile = load_profile()
        register_extensions(profile)
    stop = shlex.join([cli, "stop", "-s", session])
    print(f"Creating {session} ({args.gpu})", flush=True)
    try:
        subprocess.run([cli, "new", "-s", session, "--gpu", args.gpu], check=True)
        print(f"Session: {session}\nStop when finished: {stop}", flush=True)
        try:
            config, alias = configure(session, cli, gpu=args.gpu)
            install(config)
            print('SSH: ' + shlex.join(['ssh', '-F', str(config), alias]), flush=True)
            print(f'VS Code: Remote-SSH: Connect to Host → {alias}', flush=True)
        except OSError as exc:
            print(f'SSH setup could not complete: {exc}\n'
                  f'Retry: uv run setup_ssh.py --session {session}', file=sys.stderr)
        # SSH propagates remote failures; colab exec may exit 0 after a Python error.
        # Secrets travel over stdin rather than recorded notebook code.
        proxy = shlex.join(proxy_command(cli, session, gpu=args.gpu))
        session_hosts = Path.home() / '.config/colab-ssh/ssh' / f'{session}.known_hosts'
        ssh = ["ssh", "-o", f"ProxyCommand={proxy}",
               "-o", f"UserKnownHostsFile={session_hosts}",
               "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes",
               "-o", "ConnectTimeout=30", f"root@{session}"]
        gpu_check = gpu_setup_code(args.gpu)
        if args.restore:
            print('Configuring GPU...', flush=True)
            subprocess.run([*ssh, "python3 -c " + shlex.quote(gpu_check)], check=True)
            print('GPU ready.', flush=True)
            print('Mounting Google Drive...', flush=True)
            subprocess.run([cli, "drivemount", "-s", session, f"{remote}/{args.drive_dir}"], check=True)
            drive_check = ("from pathlib import Path; "
                           f"assert Path({(remote + '/' + args.drive_dir + '/MyDrive')!r}).is_dir(), "
                           "'Drive authorization or mount failed'")
            subprocess.run([*ssh, "python3 -c " + shlex.quote(drive_check)], check=True)
            print('Google Drive mounted.', flush=True)
            print('Restoring workspace from backup...', flush=True)
            restore_code = backup_manager.restore_remote_code(args.restore)
            res = subprocess.run([*ssh, "python3 -c " + shlex.quote(restore_code)],
                                 capture_output=True, text=True, check=True)
            for line in reversed(res.stdout.splitlines()):
                try:
                    meta = json.loads(line.strip())
                    if meta.get("status") == "ok":
                        remote = meta.get("workspace", remote)
                        break
                except json.JSONDecodeError:
                    pass
            print('Workspace restored from backup.', flush=True)
        else:
            workspace_code = (clone_code(url, remote, args.branch, args.drive_dir, authenticated=bool(token))
                              if args.repo else prepare_workspace_code(remote, args.drive_dir))
            code = gpu_check + workspace_code
            print('Configuring workspace and GPU...', flush=True)
            subprocess.run([*ssh, "python3 -c " + shlex.quote(code)],
                           input=json.dumps(token) if token else "", text=True, check=True)
            print('Workspace and GPU ready.', flush=True)
            if args.pat or args.pat_stdin:
                try:
                    save_pat_mapping(url, token, DEFAULT_AUTH)
                except (ValueError, OSError) as exc:
                    print(f'Warning: clone succeeded but PAT mapping could not be saved: {exc}',
                          file=sys.stderr)
                else:
                    print(f'Saved PAT mapping: {DEFAULT_AUTH}', flush=True)
            token = None
            if not args.skip_drive:
                print('Mounting Google Drive...', flush=True)
                subprocess.run([cli, "drivemount", "-s", session, f"{remote}/{args.drive_dir}"], check=True)
                drive_check = ("from pathlib import Path; "
                               f"assert Path({(remote + '/' + args.drive_dir + '/MyDrive')!r}).is_dir(), "
                               "'Drive authorization or mount failed'")
                subprocess.run([*ssh, "python3 -c " + shlex.quote(drive_check)], check=True)
                print('Google Drive mounted.', flush=True)
        if profile:
            print('Preparing Codex, Antigravity and VS Code preferences...', flush=True)
            apply_environment(ssh, profile)
            print('Development tools ready. Syncing agent context...', flush=True)
            sync_context(ssh)
            print('Agent context synced.', flush=True)
        print('Verifying session...', flush=True)
        verify = "from pathlib import Path\n"
        if args.repo:
            verify += f"assert Path({(remote + '/.git')!r}).is_dir(), 'Repository clone missing'\n"
        elif args.restore:
            verify += f"assert Path({remote!r}).is_dir(), 'Restored workspace missing'\n"
        subprocess.run([*ssh, "python3 -c " + shlex.quote(verify)], check=True)
    except (subprocess.CalledProcessError, KeyboardInterrupt):
        print(f"Setup interrupted or failed. Session {session} may still be active.\n"
              f"Inspect: {shlex.join([cli, 'status', '-s', session])}\nStop: {stop}", file=sys.stderr)
        return 1
    print(f"READY: {remote}")
    if not args.skip_drive:
        print(f"Drive: {remote}/{args.drive_dir}/MyDrive")
    print("Connect: " + shlex.join(ssh))
    print("Browser: " + shlex.join([cli, "url", "-s", session]))
    print(f"Stop: {stop}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
