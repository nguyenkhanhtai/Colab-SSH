#!/usr/bin/env python3
"""Create a Colab session, optionally clone GitHub, mount Google Drive, and dispatch remote jobs."""

import argparse
from dataclasses import dataclass
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
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4
import warnings

from colab_session.auth.credentials import DEFAULT_AUTH, read_auth, read_pat, save_pat_mapping
from colab_session.env.environment import apply as apply_environment, load_profile, register_extensions, sync_context
from colab_session.hardware.gpu import remote_code as gpu_setup_code
from colab_session.jobs.config import JobConfig, JobConfigDispatcher
from colab_session.jobs.manager import JobManager
from colab_session.jobs.models import JobStatus, format_job_manifest, resolve_log_file, validate_job_requirements
from colab_session.session.provisioner import (
    SessionConfig,
    SessionProvisioner,
    WorkspaceScriptGenerator,
    clone_code,
    prepare_workspace_code,
)
from colab_session.ssh.config import configure, install
from colab_session.ssh.proxy import command as proxy_command
import colab_session.storage.backup as backup_manager


def github_url(value: str) -> Tuple[str, str]:
    """Validate and parse a GitHub repository URL into clone URL and repo name."""
    match = re.fullmatch(r"https://github\.com/([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?", value)
    if not match or match[2] in {".", ".."}:
        raise argparse.ArgumentTypeError("Use https://github.com/OWNER/REPO (without credentials)")
    return f"https://github.com/{match[1]}/{match[2]}.git", match[2]


from colab_session.session.manager import ColabCliFinder, find_colab_cli, patch_colab_cli


class ManagementCommandHandler:
    """Handles non-provisioning management commands: --list, --stop, --backup, --list-backups, --serve."""

    @staticmethod
    def handle(args: argparse.Namespace, cli: str, parser: argparse.ArgumentParser) -> int:
        if args.serve:
            from colab_session.server.app import serve
            serve(args.host, args.port)
            return 0
        import colab_session.session.manager as session_manager
        if args.backup:
            try:
                session_manager.validate_name(args.backup)
                print(f"Backing up session '{args.backup}' to Google Drive...", flush=True)
                import colab_session.storage.backup as bm
                res = bm.backup(cli, args.backup)
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
                import colab_session.storage.backup as bm
                backups = bm.list_backups(cli, rows[0]['name'])
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


class JobCommandHandler:
    """Handles job execution subcommands: submit, status, logs, stop, list, run."""

    @staticmethod
    def build_job_parser() -> argparse.ArgumentParser:
        job_parser = argparse.ArgumentParser(prog="colab-ssh job", description="Manage remote jobs on Colab")
        job_subs = job_parser.add_subparsers(dest="job_action", required=True)

        submit_p = job_subs.add_parser("submit", help="Submit a job to run remotely")
        submit_p.add_argument("command", nargs="?", default="", help="Command to execute")
        submit_p.add_argument("--config", "-c", nargs="?", const="colab-job.json", help="Execute job from configuration file (default: colab-job.json)")
        submit_p.add_argument("--session", "-s", help="Target Colab session (optional if using --config)")
        submit_p.add_argument("--script", help="Path to local script to upload and run")
        submit_p.add_argument("--sync-dir", help="Local directory to upload before running")
        submit_p.add_argument("--cwd", default="/content", help="Working directory on remote VM")
        submit_p.add_argument("--download", "-dl", nargs="+", metavar="FILE", help="Remote files or patterns to download upon completion")
        submit_p.add_argument("--download-dir", default="./downloads", help="Local directory for downloaded files")
        submit_p.add_argument("--log-file", help="Path to local file where terminal output will be saved")
        submit_p.add_argument("--detached", "-d", action="store_true", default=True, help="Run in background (default: true)")
        submit_p.add_argument("--foreground", "-f", dest="detached", action="store_false", help="Run in foreground and stream output")

        run_p = job_subs.add_parser("run", help="Run a command directly on a session in foreground")
        run_p.add_argument("command", nargs="?", default="", help="Command to execute")
        run_p.add_argument("--config", "-c", nargs="?", const="colab-job.json", help="Execute job from configuration file (default: colab-job.json)")
        run_p.add_argument("--session", "-s", help="Target Colab session (optional if using --config)")
        run_p.add_argument("--cwd", default="/content", help="Working directory on remote VM")
        run_p.add_argument("--download", "-dl", nargs="+", metavar="FILE", help="Remote files or patterns to download upon completion")
        run_p.add_argument("--download-dir", default="./downloads", help="Local directory for downloaded files")
        run_p.add_argument("--log-file", help="Path to local file where terminal output will be saved")

        status_p = job_subs.add_parser("status", help="Check status of a remote job")
        status_p.add_argument("job_id", help="Job ID")
        status_p.add_argument("--session", "-s", required=True, help="Target Colab session")

        logs_p = job_subs.add_parser("logs", help="View logs of a remote job")
        logs_p.add_argument("job_id", help="Job ID")
        logs_p.add_argument("--session", "-s", required=True, help="Target Colab session")
        logs_p.add_argument("--tail", type=int, default=200, help="Number of lines to view")

        stop_p = job_subs.add_parser("stop", help="Stop a running remote job")
        stop_p.add_argument("job_id", help="Job ID")
        stop_p.add_argument("--session", "-s", required=True, help="Target Colab session")

        list_p = job_subs.add_parser("list", help="List all jobs on a session")
        list_p.add_argument("--session", "-s", required=True, help="Target Colab session")

        download_p = job_subs.add_parser("download", help="Download specified files or directories from a session")
        download_p.add_argument("files", nargs="+", help="Remote files, directories, or glob patterns to download")
        download_p.add_argument("--session", "-s", required=True, help="Target Colab session")
        download_p.add_argument("--dest", "-d", default="./downloads", help="Local destination directory (default: ./downloads)")
        download_p.add_argument("--cwd", default="/content", help="Base directory on remote Colab VM (default: /content)")

        pull_p = job_subs.add_parser("pull", help="Download output files/artifacts from a completed job")
        pull_p.add_argument("job_id", help="Job ID")
        pull_p.add_argument("--session", "-s", required=True, help="Target Colab session")
        pull_p.add_argument("--dest", "-d", help="Local destination directory (default: configured download_dir or ./downloads)")

        init_p = job_subs.add_parser("init-config", help="Generate a sample job configuration JSON file")
        init_p.add_argument("path", nargs="?", default="colab-job.json", help="Path to create config (default: colab-job.json)")

        run_cfg_p = job_subs.add_parser("run-config", aliases=["config"], help="Run a job defined in a JSON/YAML configuration file")
        run_cfg_p.add_argument("config_file", nargs="?", default="colab-job.json", help="Path to job configuration file (default: colab-job.json)")
        run_cfg_p.add_argument("--gpu", help="Override required GPU (T4, L4, G4, A100, H100)")
        run_cfg_p.add_argument("--session", "-s", help="Override target session name")
        run_cfg_p.add_argument("--log-file", help="Override path to local log file")
        run_cfg_p.add_argument("--detached", "-d", dest="detached", action="store_true", default=None, help="Run job in background")
        run_cfg_p.add_argument("--foreground", "-f", dest="detached", action="store_false", help="Run job in foreground")
        run_cfg_p.add_argument("--download", "-dl", nargs="+", metavar="FILE", help="Override files/patterns to download")
        run_cfg_p.add_argument("--download-dir", help="Override download directory")

        tree_p = job_subs.add_parser("tree", aliases=["ls"], help="Inspect remote directory tree on a Colab session")
        tree_p.add_argument("path", nargs="?", default="/content", help="Remote directory path (default: /content)")
        tree_p.add_argument("--session", "-s", required=True, help="Target Colab session")
        tree_p.add_argument("--depth", "-L", type=int, default=2, help="Max depth to traverse (default: 2)")
        tree_p.add_argument("--limit", type=int, default=10, help="Max items per directory branch (default: 10, max: 10)")
        tree_p.add_argument("--all", "-a", action="store_true", help="Include hidden files (starting with .)")
        tree_p.add_argument("--json", action="store_true", help="Output raw JSON structure")

        return job_parser

    @staticmethod
    def handle_job_cli(args: argparse.Namespace, cli: str, parser: argparse.ArgumentParser) -> int:
        jm = JobManager(cli)
        action = args.job_action

        if action == "init-config":
            target_path = Path(args.path)
            if target_path.exists():
                print(f"Error: File already exists at {target_path}", file=sys.stderr)
                return 1
            cfg = JobConfig.template()
            cfg.save(target_path)
            print(f"Sample job configuration created at {target_path}")
            return 0

        elif action in ("run-config", "config"):
            cfg_path = Path(args.config_file)
            try:
                cfg = JobConfig.load(cfg_path)
            except Exception as exc:
                print(f"Error loading configuration: {exc}", file=sys.stderr)
                return 1
            if getattr(args, "gpu", None):
                cfg.gpu = args.gpu.upper()
            if getattr(args, "session", None):
                cfg.session = args.session
            if getattr(args, "log_file", None):
                cfg.log_file = args.log_file
            if getattr(args, "detached", None) is not None:
                cfg.detached = args.detached
            if getattr(args, "download", None):
                cfg.download_files = args.download
            if getattr(args, "download_dir", None):
                cfg.download_dir = args.download_dir

            print(f"Loaded config '{cfg.name}' (GPU: {cfg.gpu}, auto_create: {cfg.auto_create})")
            dispatcher = JobConfigDispatcher(cli)
            session, was_created, result = dispatcher.dispatch(cfg)
            action_desc = "Created new" if was_created else "Reusing active"
            print(f"{action_desc} session '{session}'")
            if result is None:
                print("Session ready. No job command or script was specified.")
                return 0
            if isinstance(result, tuple):
                exit_code, _ = result
                if cfg.download_files:
                    print(f"Downloaded artifacts to: {cfg.download_dir or './downloads'}")
                saved_log = resolve_log_file(session, cfg.log_file)
                print(f"Saved terminal log to: {saved_log}")
                return exit_code
            else:
                dl_tip = f"\nPull Outputs: colab-ssh job pull {result.id} --session {session}" if cfg.download_files else ""
                print(f"Job launched in background!\n"
                      f"Job ID:  {result.id}\n"
                      f"Status:  {result.status}\n"
                      f"Logs:    colab-ssh job logs {result.id} --session {session}\n"
                      f"Status:  colab-ssh job status {result.id} --session {session}{dl_tip}")
                return 0

        elif action in ("run", "submit"):
            cfg_arg = getattr(args, "config", None)
            if cfg_arg:
                try:
                    cfg = JobConfig.load(cfg_arg)
                except Exception as exc:
                    print(f"Error loading configuration: {exc}", file=sys.stderr)
                    return 1
                if getattr(args, "session", None):
                    cfg.session = args.session
                if getattr(args, "command", ""):
                    cfg.command = args.command
                if getattr(args, "log_file", None):
                    cfg.log_file = args.log_file
                if getattr(args, "download", None):
                    cfg.download_files = args.download
                if getattr(args, "download_dir", None):
                    cfg.download_dir = args.download_dir
                if action == "run":
                    cfg.detached = False
                elif action == "submit":
                    cfg.detached = True

                print(f"Loaded config '{cfg.name}' (GPU: {cfg.gpu}, auto_create: {cfg.auto_create})")
                dispatcher = JobConfigDispatcher(cli)
                session, was_created, result = dispatcher.dispatch(cfg)
                action_desc = "Created new" if was_created else "Reusing active"
                print(f"{action_desc} session '{session}'")
                if result is None:
                    print("Session ready. No job command or script was specified.")
                    return 0
                if isinstance(result, tuple):
                    exit_code, _ = result
                    if cfg.download_files:
                        print(f"Downloaded artifacts to: {cfg.download_dir or './downloads'}")
                    saved_log = resolve_log_file(session, cfg.log_file)
                    print(f"Saved terminal log to: {saved_log}")
                    return exit_code
                else:
                    dl_tip = f"\nPull Outputs: colab-ssh job pull {result.id} --session {session}" if cfg.download_files else ""
                    print(f"Job launched in background!\n"
                          f"Job ID:  {result.id}\n"
                          f"Status:  {result.status}\n"
                          f"Logs:    colab-ssh job logs {result.id} --session {session}\n"
                          f"Status:  colab-ssh job status {result.id} --session {session}{dl_tip}")
                    return 0

            session = args.session
            if not session:
                parser.error("--session is required to run a job (or use --config)")
            cmd = getattr(args, "command", "") or ""
            script = getattr(args, "script", None)
            sync_dir = getattr(args, "sync_dir", None)
            cwd = getattr(args, "cwd", "/content") or "/content"
            detached = getattr(args, "detached", False) or (action == "submit" and getattr(args, "detached", True))
            download_files = getattr(args, "download", None)
            download_dir = getattr(args, "download_dir", None)
            log_file = getattr(args, "log_file", None)

            try:
                validate_job_requirements(
                    command=cmd,
                    script_path=script,
                    sync_dir=sync_dir,
                    session=session,
                )
            except (ValueError, FileNotFoundError, NotADirectoryError) as exc:
                print(f"Pre-flight requirement check failed:\n  {exc}", file=sys.stderr)
                return 1

            manifest = format_job_manifest(
                session=session,
                command=cmd,
                script_path=script,
                sync_dir=sync_dir,
                cwd=cwd,
                detached=detached,
                download_files=download_files,
                download_dir=download_dir,
                log_file=log_file,
            )
            print(manifest, flush=True)
            try:
                result = jm.run(
                    session=session,
                    command=cmd,
                    script_path=script,
                    sync_dir=sync_dir,
                    detached=detached,
                    cwd=cwd,
                    download_files=download_files,
                    download_dir=download_dir,
                    log_file=log_file,
                )
                if detached:
                    dl_tip = f"\nPull Outputs: colab-ssh job pull {result.id} --session {session}" if download_files else ""
                    print(f"Job launched in background!\n"
                          f"Job ID:  {result.id}\n"
                          f"Status:  {result.status}\n"
                          f"Logs:    colab-ssh job logs {result.id} --session {session}\n"
                          f"Status:  colab-ssh job status {result.id} --session {session}{dl_tip}")
                    return 0
                else:
                    exit_code, _ = result
                    if download_files:
                        print(f"Downloaded {len(download_files)} file pattern(s) to '{download_dir or './downloads'}'")
                    saved_log = resolve_log_file(session, log_file)
                    print(f"Saved terminal log to: {saved_log}")
                    return exit_code
            except Exception as exc:
                print(f"Job failed: {exc}", file=sys.stderr)
                return 1

        elif action == "status":
            session = args.session
            job_id = args.job_id
            if not session or not job_id:
                parser.error("Both --session and job_id are required")
            try:
                job = jm.status(session, job_id)
                print(f"Job ID:      {job.id}\n"
                      f"Session:     {job.session}\n"
                      f"Status:      {job.status.upper()}\n"
                      f"Exit Code:   {job.exit_code if job.exit_code is not None else 'N/A'}\n"
                      f"Started At:  {job.started_at or 'N/A'}\n"
                      f"Finished At: {job.completed_at or 'N/A'}\n"
                      f"Command:     {job.command}")
                return 0
            except Exception as exc:
                print(f"Failed to get job status: {exc}", file=sys.stderr)
                return 1

        elif action == "logs":
            session = args.session
            job_id = args.job_id
            if not session or not job_id:
                parser.error("Both --session and job_id are required")
            try:
                tail = getattr(args, "tail", 200) or 200
                logs = jm.logs(session, job_id, tail=tail)
                print(logs)
                return 0
            except Exception as exc:
                print(f"Failed to fetch logs: {exc}", file=sys.stderr)
                return 1

        elif action == "stop":
            session = args.session
            job_id = args.job_id
            if not session or not job_id:
                parser.error("Both --session and job_id are required")
            try:
                success = jm.stop(session, job_id)
                if success:
                    print(f"Job {job_id} on {session} has been stopped.")
                    return 0
                else:
                    print(f"Could not stop job {job_id} (process not found or already ended).")
                    return 1
            except Exception as exc:
                print(f"Failed to stop job: {exc}", file=sys.stderr)
                return 1

        elif action == "list":
            session = args.session
            if not session:
                parser.error("--session is required to list jobs")
            try:
                jobs = jm.list(session)
                if not jobs:
                    print(f"No jobs found on session '{session}'.")
                else:
                    print(f"{'JOB ID':<16} {'STATUS':<12} {'STARTED':<24} {'COMMAND'}")
                    print("-" * 75)
                    for j in jobs:
                        print(f"{j.get('id', ''):<16} {j.get('status', '').upper():<12} {str(j.get('started_at', ''))[:19]:<24} {j.get('command', '')}")
                return 0
            except Exception as exc:
                print(f"Failed to list jobs: {exc}", file=sys.stderr)
                return 1

        elif action == "download":
            session = args.session
            if not session:
                parser.error("--session is required to download files")
            files = args.files
            dest = args.dest
            cwd = getattr(args, "cwd", "/content") or "/content"
            print(f"Downloading {len(files)} target(s) from session '{session}' to '{dest}'...", flush=True)
            try:
                downloaded = jm.download_files(session, files, local_dest_dir=dest, remote_cwd=cwd)
                if not downloaded:
                    print(f"Notice: No files matching {files} were found on remote VM.")
                else:
                    print(f"Successfully downloaded {len(downloaded)} item(s) to '{dest}':")
                    for item in downloaded:
                        print(f"  ✓ {item}")
                return 0
            except Exception as exc:
                print(f"Download failed: {exc}", file=sys.stderr)
                return 1

        elif action == "pull":
            session = args.session
            job_id = args.job_id
            if not session or not job_id:
                parser.error("Both --session and job_id are required to pull artifacts")
            dest = getattr(args, "dest", None)
            print(f"Pulling output artifacts for job '{job_id}' from session '{session}'...", flush=True)
            try:
                downloaded = jm.pull(session, job_id, local_dest_dir=dest)
                if not downloaded:
                    print("Notice: No artifacts found or configured for this job.")
                else:
                    target_dest = dest or "configured output folder"
                    print(f"Successfully pulled {len(downloaded)} artifact(s) to '{target_dest}':")
                    for item in downloaded:
                        print(f"  ✓ {item}")
                return 0
            except Exception as exc:
                print(f"Pull failed: {exc}", file=sys.stderr)
                return 1

        elif action in ("tree", "ls"):
            session = args.session
            if not session:
                parser.error("--session is required to inspect directory")
            path = getattr(args, "path", "/content") or "/content"
            depth = getattr(args, "depth", 2) or 2
            limit = min(10, getattr(args, "limit", 10) or 10)
            show_hidden = bool(getattr(args, "all", False))
            try:
                tree_data = jm.tree(session, path=path, max_depth=depth, max_items=limit, show_hidden=show_hidden)
                if getattr(args, "json", False):
                    print(json.dumps(tree_data, indent=2))
                else:
                    from colab_session.session.explorer import RemoteDirectoryExplorer
                    print(f"Directory tree on '{session}' ({path}, max {limit} items/branch):\n")
                    print(RemoteDirectoryExplorer.render_tree(tree_data))
                return 0
            except Exception as exc:
                print(f"Failed to inspect directory: {exc}", file=sys.stderr)
                return 1

        return 0


class CredentialTokenResolver:
    """Resolves PAT tokens safely from CLI arguments, files, or user input."""

    @staticmethod
    def resolve(args: argparse.Namespace, parser: argparse.ArgumentParser, repo_url: Optional[str]) -> Optional[str]:
        token = os.environ.get("GH_TOKEN", "") if args.repo else ""
        try:
            target_auth = DEFAULT_AUTH
            read_auth_fn = read_auth
            read_pat_fn = read_pat

            if args.pat_stdin:
                token = sys.stdin.readline().strip()
                if not token:
                    parser.error("PAT from stdin cannot be empty")
            elif args.pat_file:
                token = read_pat_fn(args.pat_file)
            elif args.auth_file:
                token = read_auth_fn(args.auth_file, repo_url=repo_url)
                if not token:
                    parser.error('Auth config has no PAT for this repository')
            elif args.repo and not args.pat and not args.pat_stdin and target_auth.is_file():
                token = read_auth_fn(target_auth, repo_url=repo_url) or token
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
                return None
            if not token:
                parser.error("PAT cannot be empty")
        return token


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", type=github_url, help="Optional GitHub HTTPS repository URL")
    parser.add_argument("--gpu", default="T4", type=str.upper, choices=['T4', 'L4', 'G4', 'A100', 'H100'])
    parser.add_argument("--session", "-s", help="Name for a NEW session, or target session for commands")
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
    parser.add_argument("--run", metavar="COMMAND", help="Run a command on the target session")
    parser.add_argument("--config", "-c", nargs="?", const="colab-job.json", metavar="FILE", help="Execute job defined in a JSON or YAML configuration file (default: colab-job.json)")
    parser.add_argument("--detached", "-d", dest="detached", action="store_true", default=None, help="Run job in background")
    parser.add_argument("--foreground", "-f", dest="detached", action="store_false", help="Run job in foreground")
    parser.add_argument("--download", nargs="+", metavar="FILE", help="Download specified files or patterns from session to local machine")
    parser.add_argument("--dest", default="./downloads", help="Local destination directory for downloaded files (default: ./downloads)")
    parser.add_argument("--log-file", help="Save terminal output to a local log file")
    parser.add_argument("--tree", nargs="?", const="/content", metavar="PATH", help="Inspect remote directory tree on target session (default: /content)")

    return parser


def main(argv=None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)

    # Check for 'colab-ssh job ...' invocation
    if args_list and args_list[0] == "job":
        job_parser = JobCommandHandler.build_job_parser()
        if any(h in args_list[1:] for h in ("-h", "--help")) or len(args_list) == 1:
            job_parser.parse_args(args_list[1:] or ["--help"])
        cli = find_colab_cli()
        if cli is None:
            sys.exit("Colab CLI missing. Install with: uv tool install -e .")
        args = job_parser.parse_args(args_list[1:])
        return JobCommandHandler.handle_job_cli(args, cli, job_parser)

    # Auto-detect config file if passed as first positional argument without flags
    if args_list and not args_list[0].startswith("-") and args_list[0] != "job":
        candidate = Path(args_list[0])
        if candidate.suffix.lower() in (".json", ".yaml", ".yml") or (candidate.is_file() and not args_list[0].startswith("http")):
            args_list = ["--config", args_list[0]] + args_list[1:]

    parser = build_parser()
    if any(h in args_list for h in ("-h", "--help")):
        parser.parse_args(args_list)
    args = parser.parse_args(args_list)

    cli = find_colab_cli()
    if cli is None:
        parser.error("Colab CLI missing. Install with: uv tool install -e .")

    if args.run:
        if not args.session:
            parser.error("--session is required with --run")
        jm = JobManager(cli)
        code, _ = jm.run(args.session, args.run, detached=False, log_file=args.log_file)
        saved_log = resolve_log_file(args.session, args.log_file)
        print(f"Saved terminal log to: {saved_log}")
        return code

    if args.tree:
        if not args.session:
            parser.error("--session is required with --tree")
        jm = JobManager(cli)
        try:
            tree_data = jm.tree(args.session, path=args.tree, max_depth=2, max_items=10)
            from colab_session.session.explorer import RemoteDirectoryExplorer
            print(f"Directory tree on '{args.session}' ({args.tree}, max 10 items/branch):\n")
            print(RemoteDirectoryExplorer.render_tree(tree_data))
            return 0
        except Exception as exc:
            print(f"Failed to inspect directory: {exc}", file=sys.stderr)
            return 1

    if args.download:
        if not args.session:
            parser.error("--session is required with --download")
        jm = JobManager(cli)
        print(f"Downloading {len(args.download)} target(s) from session '{args.session}' to '{args.dest}'...", flush=True)
        try:
            downloaded = jm.download_files(args.session, args.download, local_dest_dir=args.dest)
            if not downloaded:
                print(f"Notice: No files matching {args.download} were found on remote VM.")
            else:
                print(f"Successfully downloaded {len(downloaded)} item(s) to '{args.dest}':")
                for item in downloaded:
                    print(f"  ✓ {item}")
            return 0
        except Exception as exc:
            print(f"Download failed: {exc}", file=sys.stderr)
            return 1

    if args.config:
        cfg_path = Path(args.config)
        try:
            cfg = JobConfig.load(cfg_path)
        except Exception as exc:
            parser.error(f"Configuration error: {exc}")
        if args.gpu and args.gpu != "T4":
            cfg.gpu = args.gpu
        if args.session:
            cfg.session = args.session
        if args.log_file:
            cfg.log_file = args.log_file
        if getattr(args, "detached", None) is not None:
            cfg.detached = args.detached
        if args.download:
            cfg.download_files = args.download
        if args.dest and args.dest != "./downloads":
            cfg.download_dir = args.dest
        print(f"Loaded config '{cfg.name}' (GPU: {cfg.gpu}, auto_create: {cfg.auto_create})")
        dispatcher = JobConfigDispatcher(cli)
        session, was_created, result = dispatcher.dispatch(cfg)
        action_desc = "Created new" if was_created else "Reusing active"
        print(f"{action_desc} session '{session}'")
        if result is None:
            return 0
        if isinstance(result, tuple):
            exit_code, _ = result
            if cfg.download_files:
                print(f"Downloaded artifacts to: {cfg.download_dir or './downloads'}")
            saved_log = resolve_log_file(session, cfg.log_file)
            print(f"Saved terminal log to: {saved_log}")
            return exit_code
        else:
            dl_tip = f"\nPull Outputs: colab-ssh job pull {result.id} --session {session}" if cfg.download_files else ""
            print(f"Job launched in background!\n"
                  f"Job ID:  {result.id}\n"
                  f"Status:  {result.status}\n"
                  f"Logs:    colab-ssh job logs {result.id} --session {session}\n"
                  f"Status:  colab-ssh job status {result.id} --session {session}{dl_tip}")
            return 0

    if args.list or args.stop or args.serve or args.backup or args.list_backups:
        if args.repo:
            parser.error("A repository URL cannot be combined with management commands")
        if args.restore:
            parser.error("--restore cannot be combined with management commands")
        return ManagementCommandHandler.handle(args, cli, parser)

    if args.restore:
        if args.repo:
            parser.error("A repository URL cannot be combined with --restore")
        if args.branch:
            parser.error("--branch cannot be combined with --restore")
        if args.skip_drive:
            parser.error("--skip-drive cannot be combined with --restore (Drive is required to access backups)")
        import colab_session.storage.backup as bm
        try:
            bm.validate_key(args.restore)
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
    token = CredentialTokenResolver.resolve(args, parser, url)
    if token is None and args.pat:
        return 1
    if not shutil.which("ssh"):
        parser.error("OpenSSH is required to prepare and verify the VM")
    config = SessionConfig(
        cli=cli,
        session=session,
        gpu=args.gpu,
        repo_url=url,
        repo_name=name,
        branch=args.branch,
        drive_dir=args.drive_dir,
        skip_drive=args.skip_drive,
        restore_key=args.restore,
        token=token,
        has_pat_prompt=bool(args.pat),
        has_pat_stdin=bool(args.pat_stdin),
        skip_environment=args.skip_environment,
    )
    provisioner = SessionProvisioner(config)
    return provisioner.provision()


if __name__ == "__main__":
    sys.exit(main())
