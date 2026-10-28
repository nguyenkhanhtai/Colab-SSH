"""Job runner for dispatching and tracking commands/scripts on remote Colab VMs."""
from io import BytesIO
import json
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
from typing import Any, Dict, List, Optional, Tuple

from colab_session.jobs.models import Job, JobStatus
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

        remote_collector = r'''
import glob, os, sys, tarfile

base = sys.argv[1]
patterns = sys.argv[2:]

if os.path.exists(base):
    os.chdir(base)
else:
    sys.stderr.write("BASE_DIR_NOT_FOUND\n")
    sys.exit(1)

found = []
for p in patterns:
    p = p.strip()
    if not p:
        continue
    matches = glob.glob(p, recursive=True)
    if matches:
        found.extend(matches)
    elif os.path.exists(p):
        found.append(p)

seen = set()
unique = []
for f in found:
    if f not in seen:
        seen.add(f)
        unique.append(f)

if not unique:
    sys.stderr.write("NO_MATCH\n")
    sys.exit(0)

with tarfile.open(fileobj=sys.stdout.buffer, mode="w:gz") as tar:
    for item in unique:
        tar.add(item)

sys.stderr.write("FOUND:" + ",".join(unique) + "\n")
'''

        res = subprocess.run(
            [*ssh_cmd, "python3", "-c", remote_collector, remote_base_dir, *remote_paths],
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
    def wrapper_script(job_id: str, command: str, cwd: str = "/content") -> str:
        escaped_cmd = command.strip()
        return f"""#!/usr/bin/env bash
mkdir -p /root/.colab-jobs
STATUS_FILE="/root/.colab-jobs/{job_id}.status"
LOG_FILE="/root/.colab-jobs/{job_id}.log"
PID_FILE="/root/.colab-jobs/{job_id}.pid"
META_FILE="/root/.colab-jobs/{job_id}.json"

echo "$$" > "$PID_FILE"
echo "STARTED $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$STATUS_FILE"

cd {shlex.quote(cwd)} || exit 1

# Execute command
{escaped_cmd}
EXIT_CODE=$?

echo "EXIT $EXIT_CODE $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$STATUS_FILE"
exit $EXIT_CODE
"""


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
    ) -> Tuple[int, str]:
        """Run a job synchronously in the foreground, streaming output or returning it."""
        ssh = self._ssh_command(session)
        if sync_dir:
            JobFileSynchronizer.sync_file_or_dir(ssh, sync_dir, remote_dest_dir=cwd)
        if script_path:
            remote_script = JobFileSynchronizer.sync_file_or_dir(ssh, script_path, remote_dest_dir=cwd)
            if not command:
                command = f"python3 {shlex.quote(remote_script)}"

        full_cmd = f"cd {shlex.quote(cwd)} && {command}"
        if capture_output:
            res = subprocess.run([*ssh, full_cmd], capture_output=True, text=True)
            exit_code = res.returncode
            output = res.stdout + res.stderr
        else:
            res = subprocess.run([*ssh, full_cmd])
            exit_code = res.returncode
            output = ""

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

        wrapper = JobScriptGenerator.wrapper_script(job_id, command, cwd=cwd)
        remote_wrapper_path = f"/root/.colab-jobs/{job_id}.sh"
        meta_path = f"/root/.colab-jobs/{job_id}.json"

        job = Job(
            id=job_id,
            session=session,
            command=command,
            status=JobStatus.RUNNING.value,
            cwd=cwd,
            download_files=download_files or [],
            download_dir=download_dir,
        )

        setup_and_start = f"""
mkdir -p /root/.colab-jobs
cat <<'EOF' > {shlex.quote(remote_wrapper_path)}
{wrapper}
EOF
chmod +x {shlex.quote(remote_wrapper_path)}
cat <<'EOF' > {shlex.quote(meta_path)}
{json.dumps(job.to_dict(), indent=2)}
EOF
nohup {shlex.quote(remote_wrapper_path)} > /root/.colab-jobs/{job_id}.log 2>&1 &
echo $! > /root/.colab-jobs/{job_id}.pid
"""
        subprocess.run([*ssh, "bash"], input=setup_and_start, text=True, check=True)
        return job

    def get_job_status(self, session: str, job_id: str) -> Job:
        """Query the remote job status and update its exit code / status."""
        ssh = self._ssh_command(session)
        query_script = f"""
STATUS_FILE="/root/.colab-jobs/{job_id}.status"
PID_FILE="/root/.colab-jobs/{job_id}.pid"
META_FILE="/root/.colab-jobs/{job_id}.json"

if [ -f "$META_FILE" ]; then
    cat "$META_FILE"
else
    echo '{{"id": "{job_id}", "status": "unknown"}}'
fi
echo "---STATUS---"
if [ -f "$STATUS_FILE" ]; then
    cat "$STATUS_FILE"
fi
echo "---PID---"
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    echo "$PID"
    kill -0 "$PID" 2>/dev/null && echo "ALIVE" || echo "DEAD"
fi
"""
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

        for line in status_lines:
            if line.startswith("STARTED "):
                job.started_at = line.split(" ", 1)[1]
            elif line.startswith("EXIT "):
                parts = line.split(" ", 2)
                try:
                    job.exit_code = int(parts[1])
                except (ValueError, IndexError):
                    job.exit_code = 1
                if len(parts) > 2:
                    job.completed_at = parts[2]

        if job.exit_code is not None:
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
        cmd = f"""
PID_FILE="/root/.colab-jobs/{shlex.quote(job_id)}.pid"
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    kill -TERM "$PID" 2>/dev/null || kill -KILL "$PID" 2>/dev/null
    echo "STOPPED"
else
    echo "NO_PID"
fi
"""
        res = subprocess.run([*ssh, "bash"], input=cmd, capture_output=True, text=True, check=True)
        return "STOPPED" in res.stdout

    def list_jobs(self, session: str) -> List[Dict[str, Any]]:
        """List all registered jobs on the remote session."""
        ssh = self._ssh_command(session)
        cmd = """
for f in /root/.colab-jobs/*.json; do
    [ -e "$f" ] || continue
    cat "$f"
    echo "---SEPARATOR---"
done
"""
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
    ) -> List[str]:
        """Download files specified in a job's download_files configuration."""
        job = self.get_job_status(session, job_id)
        files = job.download_files
        if not files:
            return []
        dest = local_dest_dir or job.download_dir or "./downloads"
        cwd = job.cwd or "/content"
        return self.download_files(session, remote_paths=files, local_dest_dir=dest, remote_base_dir=cwd)


