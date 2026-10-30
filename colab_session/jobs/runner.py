"""Job runner for dispatching and tracking commands/scripts on remote Colab VMs."""
from io import BytesIO
import json
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
from typing import Any, Dict, List, Optional, Tuple

from colab_session.jobs.models import Job, JobStatus, resolve_log_file
from colab_session.jobs.quota import parse_timeout_to_seconds, parse_vram_to_mb
from colab_session.resources import read_resource, render_template
from colab_session.storage.backup import ssh_command_for_session


class JobFileSynchronizer:
    """Uploads local files or directories to the remote Colab VM and downloads remote artifacts."""

    @staticmethod
    def sync_file_or_dir(ssh_cmd: List[str], local_path: Path | str, remote_dest_dir: str = "/content") -> str:
        """Upload a local file or directory to remote_dest_dir and return remote file path."""
        path = Path(local_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Local path does not exist: {path}")

        archive = BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as tar:
            if path.is_dir():
                for item in path.iterdir():
                    if item.name in {".venv", ".venv-colab", "__pycache__", ".git"}:
                        continue
                    tar.add(item, arcname=item.name)
                remote_target = remote_dest_dir
            else:
                tar.add(path, arcname=path.name)
                remote_target = f"{remote_dest_dir}/{path.name}"

        mkdir_cmd = f"mkdir -p {shlex.quote(remote_dest_dir)} && tar -xzf - -C {shlex.quote(remote_dest_dir)}"
        subprocess.run([*ssh_cmd, mkdir_cmd], input=archive.getvalue(), check=True)
        return remote_target

    @staticmethod
    def download_files_or_dirs(
        ssh_cmd: List[str],
        remote_paths: List[str],
        local_dest_dir: Path | str,
        remote_base_dir: str = "/content",
    ) -> List[str]:
        """
        Download specified files or directories from remote Colab VM to local_dest_dir.
        Supports exact paths, subdirectories, and glob patterns relative to remote_base_dir.
        Returns list of downloaded file/directory names.
        """
        if not remote_paths:
            return []

        dest = Path(local_dest_dir).expanduser().resolve()
        dest.mkdir(parents=True, exist_ok=True)

        remote_collector = read_resource("scripts", "remote_collector.py")

        res = subprocess.run(
            [*ssh_cmd, shlex.join(["python3", "-c", remote_collector, remote_base_dir, *remote_paths])],
            capture_output=True,
            check=True,
        )

        stderr_str = res.stderr.decode("utf-8", errors="replace") if isinstance(res.stderr, bytes) else str(res.stderr)
        if "NO_MATCH" in stderr_str:
            return []

        found_items = []
        for line in stderr_str.splitlines():
            if line.startswith("FOUND:"):
                found_items = [x for x in line[6:].split(",") if x]

        if not res.stdout:
            return []

        archive = BytesIO(res.stdout)
        with tarfile.open(fileobj=archive, mode="r:gz") as tar:
            for member in tar.getmembers():
                target_path = (dest / member.name).resolve()
                try:
                    target_path.relative_to(dest)
                except ValueError:
                    raise ValueError(f"Unsafe path detected in downloaded archive: {member.name}")
            if hasattr(tarfile, "data_filter"):
                tar.extractall(path=dest, filter="data")
            else:
                tar.extractall(path=dest)

        return found_items


class JobScriptGenerator:
    """Generates wrapper bash scripts for background jobs."""

    @staticmethod
    def wrapper_script(
        job_id: str,
        command: str,
        cwd: str = "/content",
        env: Optional[Dict[str, str]] = None,
        setup_command: Optional[str] = None,
        vram_mb: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
    ) -> str:
        escaped_cmd = command.strip()
        custom_env_lines = []
        if env:
            for k, v in env.items():
                safe_k = re.sub(r"[^A-Za-z0-9_]", "", str(k))
                if safe_k:
                    custom_env_lines.append(f"export {safe_k}={shlex.quote(str(v))}")
        custom_env_str = ("\n" + "\n".join(custom_env_lines) + "\n") if custom_env_lines else ""

        setup_block = ""
        if setup_command and setup_command.strip():
            setup_block = (
                '# Setup environment dependencies before main execution\n'
                'echo "SETUP_START $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$STATUS_FILE"\n'
                f"{setup_command.strip()}\n"
                'SETUP_EXIT=$?\n'
                'if [ $SETUP_EXIT -ne 0 ]; then\n'
                '    echo "EXIT $SETUP_EXIT $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$STATUS_FILE"\n'
                '    exit $SETUP_EXIT\n'
                'fi\n'
            )

        context = {
            "JOB_ID": job_id,
            "CUSTOM_ENV": custom_env_str,
            "CWD": shlex.quote(cwd),
            "SETUP_BLOCK": setup_block,
            "COMMAND": escaped_cmd,
            "VRAM_LIMIT_MB": str(vram_mb) if vram_mb else "",
            "TIMEOUT_SECS": str(timeout_seconds) if timeout_seconds else "",
        }
        return render_template("scripts", "job_wrapper.sh.template", context=context)


class RemoteJobRunner:
    """Manages execution, logging, and status tracking of jobs on Colab sessions."""

    def __init__(self, cli: str):
        self.cli = cli

    def _ssh_command(self, session: str) -> List[str]:
        return ssh_command_for_session(self.cli, session)

    def run_sync(
        self,
        session: str,
        command: str,
        script_path: Optional[str | Path] = None,
        sync_dir: Optional[str | Path] = None,
        cwd: str = "/content",
        capture_output: bool = False,
        download_files: Optional[List[str]] = None,
        download_dir: Optional[str | Path] = None,
        env: Optional[Dict[str, str]] = None,
        setup_command: Optional[str] = None,
        log_file: Optional[str | Path] = None,
    ) -> Tuple[int, str]:
        """Run a job synchronously in the foreground, streaming output or returning it."""
        ssh = self._ssh_command(session)
        if sync_dir:
            JobFileSynchronizer.sync_file_or_dir(ssh, sync_dir, remote_dest_dir=cwd)
        if script_path:
            remote_script = JobFileSynchronizer.sync_file_or_dir(ssh, script_path, remote_dest_dir=cwd)
            if not command:
                command = f"python3 {shlex.quote(remote_script)}"

        env_exports = [
            "export PATH=\"/root/.local/bin:/usr/local/cuda/bin:$PATH\"",
            "export LD_LIBRARY_PATH=\"/usr/lib64-nvidia:/usr/local/cuda/lib64:${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}\"",
            "export PYTHONUNBUFFERED=1",
        ]
        if env:
            for k, v in env.items():
                safe_k = re.sub(r"[^A-Za-z0-9_]", "", str(k))
                if safe_k:
                    env_exports.append(f"export {safe_k}={shlex.quote(str(v))}")
        env_cmd = "; ".join(env_exports) + "; "
        setup_cmd = f"{setup_command.strip()} && " if setup_command and setup_command.strip() else ""
        full_cmd = f"{env_cmd}cd {shlex.quote(cwd)} && {setup_cmd}{command}"

        target_log_path = resolve_log_file(session, log_file)
        target_log_path.parent.mkdir(parents=True, exist_ok=True)

        if capture_output:
            res = subprocess.run([*ssh, full_cmd], capture_output=True, text=True)
            exit_code = res.returncode
            output = res.stdout + res.stderr
            target_log_path.write_text(output, encoding="utf-8")
        else:
            proc = subprocess.Popen(
                [*ssh, full_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            output_lines = []
            if proc.stdout is not None:
                with open(target_log_path, "w", encoding="utf-8") as f_log:
                    for line in proc.stdout:
                        sys.stdout.write(line)
                        sys.stdout.flush()
                        f_log.write(line)
                        f_log.flush()
                        output_lines.append(line)
            proc.wait()
            exit_code = proc.returncode
            output = "".join(output_lines)

        if download_files:
            dest_dir = download_dir or "./downloads"
            JobFileSynchronizer.download_files_or_dirs(
                ssh_cmd=ssh,
                remote_paths=download_files,
                local_dest_dir=dest_dir,
                remote_base_dir=cwd,
            )

        return exit_code, output

    def submit_detached(
        self,
        session: str,
        command: str,
        script_path: Optional[str | Path] = None,
        sync_dir: Optional[str | Path] = None,
        cwd: str = "/content",
        download_files: Optional[List[str]] = None,
        download_dir: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        setup_command: Optional[str] = None,
        log_file: Optional[str] = None,
        vram: Optional[str | int] = None,
        timeout: Optional[str | int] = None,
    ) -> Job:
        """Submit a job to run remotely in the background (detached mode)."""
        job_id = Job.create_id()
        ssh = self._ssh_command(session)

        if sync_dir:
            JobFileSynchronizer.sync_file_or_dir(ssh, sync_dir, remote_dest_dir=cwd)
        if script_path:
            remote_script = JobFileSynchronizer.sync_file_or_dir(ssh, script_path, remote_dest_dir=cwd)
            if not command:
                command = f"python3 {shlex.quote(remote_script)}"

        vram_mb = parse_vram_to_mb(vram)
        timeout_seconds = parse_timeout_to_seconds(timeout)

        wrapper = JobScriptGenerator.wrapper_script(
            job_id,
            command,
            cwd=cwd,
            env=env,
            setup_command=setup_command,
            vram_mb=vram_mb,
            timeout_seconds=timeout_seconds,
        )
        remote_wrapper_path = f"/root/.colab-jobs/{job_id}.sh"
        meta_path = f"/root/.colab-jobs/{job_id}.json"

        resolved_log = str(resolve_log_file(session, log_file, job_id=job_id))
        job = Job(
            id=job_id,
            session=session,
            command=command,
            status=JobStatus.RUNNING.value,
            cwd=cwd,
            download_files=download_files or [],
            download_dir=download_dir,
            env=env or {},
            setup_command=setup_command,
            log_file=resolved_log,
            vram=str(vram) if vram is not None else None,
            vram_mb=vram_mb,
            timeout=str(timeout) if timeout is not None else None,
            timeout_seconds=timeout_seconds,
        )

        setup_and_start = render_template(
            "scripts",
            "job_start.sh.template",
            context={
                "WRAPPER_PATH": shlex.quote(remote_wrapper_path),
                "WRAPPER_CONTENT": wrapper,
                "META_PATH": shlex.quote(meta_path),
                "META_JSON": json.dumps(job.to_dict(), indent=2),
                "JOB_ID": job_id,
                "SITECUSTOMIZE_CONTENT": read_resource("scripts", "sitecustomize.py.template"),
                "QUOTA_MANAGER_CONTENT": read_resource("scripts", "remote_quota_manager.py"),
            },
        )
        subprocess.run([*ssh, "bash"], input=setup_and_start, text=True, check=True)
        return job

    def get_job_status(self, session: str, job_id: str) -> Job:
        """Query the remote job status and update its exit code / status."""
        ssh = self._ssh_command(session)
        query_script = render_template(
            "scripts",
            "job_query_status.sh.template",
            context={"JOB_ID": job_id},
        )
        res = subprocess.run([*ssh, "bash"], input=query_script, capture_output=True, text=True, check=True)
        output = res.stdout

        meta_part, _, rest = output.partition("---STATUS---")
        status_part, _, pid_part = rest.partition("---PID---")

        try:
            meta = json.loads(meta_part.strip())
            job = Job.from_dict(meta)
        except Exception:
            job = Job(id=job_id, session=session, command="")

        # Check PID alive
        is_alive = "ALIVE" in pid_part
        status_lines = [ln.strip() for ln in status_part.strip().splitlines() if ln.strip()]

        is_timed_out = False
        for line in status_lines:
            if line.startswith("STARTED "):
                job.started_at = line.split(" ", 1)[1]
            elif line.startswith("TIMED_OUT"):
                is_timed_out = True
            elif line.startswith("EXIT "):
                parts = line.split(" ", 2)
                try:
                    job.exit_code = int(parts[1])
                except (ValueError, IndexError):
                    job.exit_code = 1
                if len(parts) > 2:
                    job.completed_at = parts[2]

        if is_timed_out or job.exit_code == 124:
            job.status = JobStatus.TIMED_OUT.value
        elif job.exit_code is not None:
            job.status = JobStatus.COMPLETED.value if job.exit_code == 0 else JobStatus.FAILED.value
        elif is_alive:
            job.status = JobStatus.RUNNING.value
        else:
            job.status = JobStatus.STOPPED.value

        return job

    def get_job_logs(self, session: str, job_id: str, tail: int = 200) -> str:
        """Fetch the log output of a remote job."""
        ssh = self._ssh_command(session)
        cmd = f"tail -n {int(tail)} /root/.colab-jobs/{shlex.quote(job_id)}.log 2>/dev/null || echo 'No logs found.'"
        res = subprocess.run([*ssh, cmd], capture_output=True, text=True, check=True)
        return res.stdout

    def stop_job(self, session: str, job_id: str) -> bool:
        """Terminate a running remote job process."""
        ssh = self._ssh_command(session)
        cmd = render_template(
            "scripts",
            "job_stop.sh.template",
            context={"JOB_ID": job_id},
        )
        res = subprocess.run([*ssh, "bash"], input=cmd, capture_output=True, text=True, check=True)
        return "STOPPED" in res.stdout

    def list_jobs(self, session: str) -> List[Dict[str, Any]]:
        """List all registered jobs on the remote session."""
        ssh = self._ssh_command(session)
        cmd = read_resource("scripts", "job_list.sh")
        res = subprocess.run([*ssh, "bash"], input=cmd, capture_output=True, text=True, check=True)
        items = []
        for part in res.stdout.split("---SEPARATOR---"):
            cleaned = part.strip()
            if not cleaned:
                continue
            try:
                data = json.loads(cleaned)
                items.append(data)
            except Exception:
                pass
        return items

    def download_files(
        self,
        session: str,
        remote_paths: List[str],
        local_dest_dir: Path | str = "./downloads",
        remote_base_dir: str = "/content",
    ) -> List[str]:
        """Download specified files or directories from a Colab session."""
        ssh = self._ssh_command(session)
        return JobFileSynchronizer.download_files_or_dirs(
            ssh_cmd=ssh,
            remote_paths=remote_paths,
            local_dest_dir=local_dest_dir,
            remote_base_dir=remote_base_dir,
        )

    def pull_job_artifacts(
        self,
        session: str,
        job_id: str,
        local_dest_dir: Optional[Path | str] = None,
        save_log: bool = True,
    ) -> List[str]:
        """Download files and terminal logs specified in a job's configuration."""
        job = self.get_job_status(session, job_id)
        files = list(job.download_files or [])
        dest = local_dest_dir or job.download_dir or "./downloads"
        cwd = job.cwd or "/content"
        downloaded = []
        if files:
            downloaded.extend(self.download_files(session, remote_paths=files, local_dest_dir=dest, remote_base_dir=cwd))

        if save_log:
            try:
                logs = self.get_job_logs(session, job_id, tail=100000)
                if logs and logs.strip() != "No logs found.":
                    log_target = resolve_log_file(session, job.log_file, job_id=job_id)
                    log_target.parent.mkdir(parents=True, exist_ok=True)
                    log_target.write_text(logs, encoding="utf-8")
                    downloaded.append(str(log_target))
            except Exception:
                pass

        return downloaded

    def inspect_tree(
        self,
        session: str,
        path: str = "/content",
        max_depth: int = 2,
        max_items_per_branch: int = 10,
        show_hidden: bool = False,
    ) -> Dict[str, Any]:
        """
        Inspect directory tree structure on a remote Colab VM.
        Caps number of entries per branch to max_items_per_branch (default: 10).
        """
        from colab_session.session.explorer import RemoteDirectoryExplorer
        explorer = RemoteDirectoryExplorer(self.cli)
        return explorer.inspect_tree(
            session=session,
            path=path,
            max_depth=max_depth,
            max_items_per_branch=max_items_per_branch,
            show_hidden=show_hidden,
        )


