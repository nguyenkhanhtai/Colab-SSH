"""Session provisioning and remote workspace orchestration."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

from colab_session.auth.credentials import DEFAULT_AUTH, save_pat_mapping
from colab_session.env.environment import apply as apply_environment, load_profile, register_extensions, sync_context
from colab_session.hardware.gpu import remote_code as gpu_setup_code
from colab_session.resources import render_template
from colab_session.ssh.config import configure, install
from colab_session.ssh.proxy import command as proxy_command


class WorkspaceScriptGenerator:
    """Generates remote python scripts for workspace cloning and setup (Single Responsibility)."""

    @staticmethod
    def clone_code(url: str, remote: str, branch: Optional[str], drive_dir: str, authenticated: bool = False) -> str:
        command = ["git", "clone"]
        if branch:
            command += ["--branch", branch]
        command += ["--", url, remote]
        clone = f'subprocess.run({command!r}, check=True, env={{**os.environ, "GIT_TERMINAL_PROMPT": "0"}})'
        if authenticated:
            auth_cmd = [command[0], '-c', 'credential.helper=', *command[1:]]
            clone = render_template("scripts", "git_clone_auth.py.template", context={"AUTH_COMMAND": repr(auth_cmd)})

        exclude_line = repr(f"\n/{drive_dir}/\n")
        return render_template(
            "scripts",
            "git_clone.py.template",
            context={
                "REMOTE": repr(remote),
                "CLONE_COMMAND": clone,
                "DRIVE_DIR": repr(drive_dir),
                "EXCLUDE_LINE": exclude_line,
            },
        )

    @staticmethod
    def prepare_workspace_code(remote: str, drive_dir: str) -> str:
        return render_template(
            "scripts",
            "prepare_workspace.py.template",
            context={
                "REMOTE": repr(remote),
                "DRIVE_DIR": repr(drive_dir),
            },
        )


def clone_code(url: str, remote: str, branch: Optional[str], drive_dir: str, authenticated: bool = False) -> str:
    return WorkspaceScriptGenerator.clone_code(url, remote, branch, drive_dir, authenticated)


def prepare_workspace_code(remote: str, drive_dir: str) -> str:
    return WorkspaceScriptGenerator.prepare_workspace_code(remote, drive_dir)


@dataclass
class SessionConfig:
    """Configuration parameter object for session provisioning."""
    cli: str
    session: str
    gpu: str
    repo_url: Optional[str]
    repo_name: Optional[str]
    branch: Optional[str]
    drive_dir: str
    skip_drive: bool
    restore_key: Optional[str]
    token: Optional[str]
    has_pat_prompt: bool
    has_pat_stdin: bool
    skip_environment: bool


class SessionProvisioner:
    """Orchestrates end-to-end VM allocation, SSH setup, workspace prep, and verification."""

    def __init__(self, config: SessionConfig):
        self.config = config
        self.remote = f"/content/{config.repo_name}" if config.repo_name else "/content"
        self.stop_cmd = shlex.join([config.cli, "stop", "-s", config.session])

    def build_ssh_command(self) -> List[str]:
        proxy = shlex.join(proxy_command(self.config.cli, self.config.session, gpu=self.config.gpu))
        session_hosts = Path.home() / '.config/colab-ssh/ssh' / f'{self.config.session}.known_hosts'
        return ["ssh", "-F", "/dev/null", "-o", f"ProxyCommand={proxy}",
                "-o", f"UserKnownHostsFile={session_hosts}",
                "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=30", f"root@{self.config.session}"]

    def provision(self) -> int:
        run_func = subprocess.run
        conf_func = configure
        inst_func = install
        load_prof = load_profile
        reg_ext = register_extensions
        apply_env = apply_environment
        sync_ctx = sync_context
        save_pat_fn = save_pat_mapping
        gpu_code_fn = gpu_setup_code
        target_auth = DEFAULT_AUTH

        profile = None
        if not self.config.skip_environment:
            profile = load_prof()
            reg_ext(profile)
        print(f"Creating {self.config.session} ({self.config.gpu})", flush=True)
        try:
            run_func([self.config.cli, "new", "-s", self.config.session, "--gpu", self.config.gpu], check=True)
            print(f"Session: {self.config.session}\nStop when finished: {self.stop_cmd}", flush=True)
            try:
                ssh_conf, alias = conf_func(self.config.session, self.config.cli, gpu=self.config.gpu)
                inst_func(ssh_conf)
                print('SSH: ' + shlex.join(['ssh', '-F', str(ssh_conf), alias]), flush=True)
                print(f'VS Code: Remote-SSH: Connect to Host → {alias}', flush=True)
            except OSError as exc:
                print(f'SSH setup could not complete: {exc}\n'
                      f'Retry: colab-ssh --session {self.config.session}', file=sys.stderr)
            ssh = self.build_ssh_command()
            gpu_check = gpu_code_fn(self.config.gpu)
            if self.config.restore_key:
                self._provision_restore(ssh, gpu_check, run_func)
            else:
                self._provision_workspace(ssh, gpu_check, run_func, save_pat_fn, target_auth)
            if profile:
                print('Preparing Codex, Antigravity and VS Code preferences...', flush=True)
                apply_env(ssh, profile)
                print('Development tools ready. Syncing agent context...', flush=True)
                sync_ctx(ssh)
                print('Agent context synced.', flush=True)
            print('Verifying session...', flush=True)
            verify = "from pathlib import Path\n"
            if self.config.repo_url:
                verify += f"assert Path({(self.remote + '/.git')!r}).is_dir(), 'Repository clone missing'\n"
            elif self.config.restore_key:
                verify += f"assert Path({self.remote!r}).is_dir(), 'Restored workspace missing'\n"
            run_func([*ssh, "python3 -c " + shlex.quote(verify)], check=True)
        except (subprocess.CalledProcessError, KeyboardInterrupt):
            print(f"Setup interrupted or failed. Session {self.config.session} may still be active.\n"
                  f"Inspect: {shlex.join([self.config.cli, 'status', '-s', self.config.session])}\nStop: {self.stop_cmd}", file=sys.stderr)
            return 1
        print(f"READY: {self.remote}")
        if not self.config.skip_drive:
            print(f"Drive: {self.remote}/{self.config.drive_dir}/MyDrive")
        print("Connect: " + shlex.join(ssh))
        print("Browser: " + shlex.join([self.config.cli, "url", "-s", self.config.session]))
        print(f"Stop: {self.stop_cmd}")
        return 0

    def _provision_restore(self, ssh: List[str], gpu_check: str, run_func) -> None:
        print('Configuring GPU...', flush=True)
        run_func([*ssh, "python3 -c " + shlex.quote(gpu_check)], check=True)
        print('GPU ready.', flush=True)
        print('Mounting Google Drive...', flush=True)
        run_func([self.config.cli, "drivemount", "-s", self.config.session, f"{self.remote}/{self.config.drive_dir}"], check=True)
        drive_check = ("from pathlib import Path; "
                       f"assert Path({(self.remote + '/' + self.config.drive_dir + '/MyDrive')!r}).is_dir(), "
                       "'Drive authorization or mount failed'")
        run_func([*ssh, "python3 -c " + shlex.quote(drive_check)], check=True)
        print('Google Drive mounted.', flush=True)
        print('Restoring workspace from backup...', flush=True)
        import colab_session.storage.backup as bm
        restore_code = bm.restore_remote_code(self.config.restore_key)
        res = run_func([*ssh, "python3 -c " + shlex.quote(restore_code)],
                       capture_output=True, text=True, check=True)
        for line in reversed(res.stdout.splitlines()):
            try:
                meta = json.loads(line.strip())
                if meta.get("status") == "ok":
                    self.remote = meta.get("workspace", self.remote)
                    break
            except json.JSONDecodeError:
                pass
        print('Workspace restored from backup.', flush=True)

    def _provision_workspace(self, ssh: List[str], gpu_check: str, run_func, save_pat_fn, target_auth) -> None:
        workspace_code = (clone_code(self.config.repo_url, self.remote, self.config.branch, self.config.drive_dir, authenticated=bool(self.config.token))
                          if self.config.repo_url else prepare_workspace_code(self.remote, self.config.drive_dir))
        code = gpu_check + workspace_code
        print('Configuring workspace and GPU...', flush=True)
        run_func([*ssh, "python3 -c " + shlex.quote(code)],
                 input=json.dumps(self.config.token) if self.config.token else "", text=True, check=True)
        print('Workspace and GPU ready.', flush=True)
        if self.config.has_pat_prompt or self.config.has_pat_stdin:
            try:
                save_pat_fn(self.config.repo_url, self.config.token, target_auth)
            except (ValueError, OSError) as exc:
                print(f'Warning: clone succeeded but PAT mapping could not be saved: {exc}',
                      file=sys.stderr)
            else:
                print(f'Saved PAT mapping: {target_auth}', flush=True)
        self.config.token = None
        if not self.config.skip_drive:
            print('Mounting Google Drive...', flush=True)
            run_func([self.config.cli, "drivemount", "-s", self.config.session, f"{self.remote}/{self.config.drive_dir}"], check=True)
            drive_check = ("from pathlib import Path; "
                           f"assert Path({(self.remote + '/' + self.config.drive_dir + '/MyDrive')!r}).is_dir(), "
                           "'Drive authorization or mount failed'")
            run_func([*ssh, "python3 -c " + shlex.quote(drive_check)], check=True)
            print('Google Drive mounted.', flush=True)
