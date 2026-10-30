"""Facade manager for job submissions and monitoring."""
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from colab_session.jobs.models import Job, JobStatus, validate_job_requirements
from colab_session.jobs.runner import RemoteJobRunner
from colab_session.session.manager import validate_name


class JobManager:
    """Coordinates job executions, status polling, and lifecycle operations."""

    def __init__(self, cli: str):
        self.cli = cli
        self.runner = RemoteJobRunner(cli)

    def run(
        self,
        session: str,
        command: str,
        script_path: Optional[str | Path] = None,
        sync_dir: Optional[str | Path] = None,
        detached: bool = False,
        cwd: str = "/content",
        capture_output: bool = False,
        download_files: Optional[List[str]] = None,
        download_dir: Optional[str | Path] = None,
        env: Optional[Dict[str, str]] = None,
        setup_command: Optional[str] = None,
        log_file: Optional[str | Path] = None,
        vram: Optional[str | int] = None,
        timeout: Optional[str | int] = None,
    ) -> Job | Tuple[int, str]:
        validate_name(session)
        validate_job_requirements(
            command=command,
            script_path=script_path,
            sync_dir=sync_dir,
            session=session,
        )
        if detached:
            return self.runner.submit_detached(
                session=session,
                command=command,
                script_path=script_path,
                sync_dir=sync_dir,
                cwd=cwd,
                download_files=download_files,
                download_dir=str(download_dir) if download_dir else None,
                env=env,
                setup_command=setup_command,
                log_file=str(log_file) if log_file else None,
                vram=vram,
                timeout=timeout,
            )
        else:
            return self.runner.run_sync(
                session=session,
                command=command,
                script_path=script_path,
                sync_dir=sync_dir,
                cwd=cwd,
                capture_output=capture_output,
                download_files=download_files,
                download_dir=download_dir,
                env=env,
                setup_command=setup_command,
                log_file=log_file,
            )

    def download_files(
        self,
        session: str,
        remote_paths: List[str],
        local_dest_dir: str | Path = "./downloads",
        remote_cwd: str = "/content",
    ) -> List[str]:
        """Download specified remote files or directories from a Colab session."""
        validate_name(session)
        return self.runner.download_files(
            session=session,
            remote_paths=remote_paths,
            local_dest_dir=local_dest_dir,
            remote_base_dir=remote_cwd,
        )

    def pull(
        self,
        session: str,
        job_id: str,
        local_dest_dir: Optional[str | Path] = None,
        save_log: bool = True,
    ) -> List[str]:
        """Pull artifacts/download_files and terminal logs specified by a remote job."""
        validate_name(session)
        return self.runner.pull_job_artifacts(
            session=session,
            job_id=job_id,
            local_dest_dir=local_dest_dir,
            save_log=save_log,
        )

    def status(self, session: str, job_id: str) -> Job:
        validate_name(session)
        return self.runner.get_job_status(session, job_id)

    def logs(self, session: str, job_id: str, tail: int = 200) -> str:
        validate_name(session)
        return self.runner.get_job_logs(session, job_id, tail=tail)

    def stop(self, session: str, job_id: str) -> bool:
        validate_name(session)
        return self.runner.stop_job(session, job_id)

    def list(self, session: str) -> List[Dict[str, Any]]:
        validate_name(session)
        return self.runner.list_jobs(session)

    def tree(
        self,
        session: str,
        path: str = "/content",
        max_depth: int = 2,
        max_items: int = 10,
        show_hidden: bool = False,
    ) -> Dict[str, Any]:
        """Inspect directory tree on remote VM, showing at most max_items per branch."""
        validate_name(session)
        return self.runner.inspect_tree(
            session=session,
            path=path,
            max_depth=max_depth,
            max_items_per_branch=max_items,
            show_hidden=show_hidden,
        )

