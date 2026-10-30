"""Local web control plane for Colab SSH sessions and job dispatching."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from colab_session.jobs.manager import JobManager
import colab_session.session.manager as session_manager
from colab_session.session.manager import alias_for, find_colab_cli
import colab_session.storage.backup as backup_manager
from colab_session.storage.backup import validate_key

from colab_session.resources import read_resource


def get_dashboard_html() -> str:
    """Load dashboard HTML template from package resources."""
    return read_resource("server", "templates", "dashboard.html")


HTML = get_dashboard_html()


class LogStatusParser:
    """Parses provisioning log output into stages, progress, and auth URLs (Single Responsibility)."""

    STAGES = [
        ('Creating runtime', 8, 'Creating '),
        ('Runtime allocated', 18, 'Session READY.'),
        ('SSH configured', 25, 'SSH:'),
        ('Configuring workspace and GPU', 32, 'Configuring workspace and GPU...'),
        ('Workspace and GPU ready', 44, 'Workspace and GPU ready.'),
        ('Mounting Google Drive', 46, 'Mounting Google Drive...'),
        ('Google Drive mounted', 52, 'Google Drive mounted.'),
        ('Restoring workspace from backup', 54, 'Restoring workspace from backup...'),
        ('Workspace restored', 58, 'Workspace restored from backup.'),
        ('Installing development tools', 60, 'Preparing Codex, Antigravity'),
        ('Development tools ready', 70, 'Environment ready.'),
        ('Syncing agent context', 78, 'Syncing agent context...'),
        ('Agent context synced', 90, 'Agent context synced.'),
        ('Verifying session', 96, 'Verifying session...'),
        ('Ready', 100, 'READY:'),
    ]

    @classmethod
    def read_tail(cls, log_path: Path, max_bytes: int = 131072) -> str:
        try:
            with log_path.open('rb') as stream:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - max_bytes))
                return stream.read().decode(errors='replace')
        except FileNotFoundError:
            return ''

    @classmethod
    def parse(cls, output: str, exit_code: Optional[int], confirmed: bool) -> Tuple[str, str, int, bool, Optional[str]]:
        urls = re.findall(r'https://accounts\.google\.com/[^\s]+', output)
        running = exit_code is None
        awaiting = bool(urls and running and not confirmed)
        stage, progress = 'Queued', 3
        for label, percent, marker in cls.STAGES:
            if marker in output:
                stage, progress = label, percent
        status = 'provisioning'
        if awaiting:
            status, stage, progress = 'awaiting_authorization', 'Waiting for Drive authorization', 46
        elif exit_code == 0 or 'READY:' in output:
            status, stage, progress = 'ready', 'Ready', 100
        elif exit_code is not None:
            status, stage, progress = 'failed', 'Provisioning failed', 100
        auth_url = urls[-1] if awaiting else None
        return status, stage, progress, awaiting, auth_url


class App:
    """Control plane service for provisioning jobs, remote jobs, and dashboard views."""

    def __init__(self, cli: str):
        self.cli = cli
        self.logs = Path.home() / '.config/colab-ssh/logs'
        self.logs.mkdir(parents=True, exist_ok=True)
        self.jobs = {}
        self.jobs_lock = threading.Lock()
        self.job_manager = JobManager(cli)

    def create(self, payload: Dict[str, Any]) -> str:
        gpu = str(payload.get('gpu') or 'T4').upper()
        if gpu not in {'T4', 'L4', 'G4', 'A100', 'H100'}:
            raise ValueError('Unsupported GPU')
        name = str(payload.get('session') or '').strip()
        if not name:
            from datetime import datetime, timezone
            from uuid import uuid4
            name = 'colab-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:6]
        session_manager.validate_name(name)
        if name in session_manager.active_names():
            raise ValueError('Session already exists')

        target_script = Path(__file__).parent.parent / 'cli/main.py'
        cmd = [sys.executable, str(target_script), '--session', name, '--gpu', gpu]

        mount_drive = bool(payload.get('mount_drive', False))
        restore_key = str(payload.get('restore_key') or '').strip()
        if restore_key:
            validate_key(restore_key)
            cmd += ['--restore', restore_key]
            mount_drive = True
        elif not mount_drive:
            cmd.append('--skip-drive')
        repository = payload.get('repository') or {}
        if restore_key and repository.get('enabled'):
            raise ValueError('Cannot initialize from GitHub when restoring from a backup')
        token = ''
        if repository.get('enabled'):
            repo = str(repository.get('url') or '').strip()
            if not repo:
                raise ValueError('GitHub repository URL is required')
            branch = str(repository.get('branch') or '').strip()
            if branch:
                cmd += ['--branch', branch]
            credential = repository.get('credential') or 'mapped'
            if credential == 'pat':
                token = str(repository.get('pat') or '').strip()
                if not token:
                    raise ValueError('GitHub PAT is required')
                cmd.append('--pat-stdin')
            elif credential != 'mapped':
                raise ValueError('Unsupported credential method')
            cmd.append(repo)
        log_file = self.logs / f'{name}.log'
        log = log_file.open('wb')
        needs_input = bool(token) or mount_drive
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE if needs_input else subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        if token:
            process.stdin.write((token + '\n').encode())
            process.stdin.flush()
        token = ''
        if needs_input and not mount_drive:
            process.stdin.close()
        with self.jobs_lock:
            self.jobs[name] = {'process': process, 'log': log_file,
                               'mount_drive': mount_drive, 'confirmed': False, 'gpu': gpu}
        log.close()
        return name

    def backup(self, name: str) -> Dict[str, Any]:
        session_manager.validate_name(name)
        return backup_manager.backup(self.cli, name)

    def job_status(self, name: str) -> Dict[str, Any]:
        session_manager.validate_name(name)
        with self.jobs_lock:
            job = self.jobs.get(name)
        if not job:
            raise ValueError('Provisioning job not found')
        output = LogStatusParser.read_tail(job['log'])
        exit_code = job['process'].poll()
        running = exit_code is None
        status, stage, progress, awaiting, auth_url = LogStatusParser.parse(
            output, exit_code, job['confirmed']
        )
        return {'session': name, 'gpu': job['gpu'], 'running': running,
                'status': status, 'stage': stage, 'progress': progress,
                'awaiting_drive_authorization': awaiting,
                'authorization_url': auth_url,
                'finished': not running, 'exit_code': exit_code}

    def dashboard_sessions(self) -> List[Dict[str, Any]]:
        rows = {item['name']: item for item in session_manager.sessions(cli=self.cli)}
        with self.jobs_lock:
            names = list(self.jobs)
        stale = []
        for name in names:
            job = self.job_status(name)
            if job['finished'] and name not in rows:
                stale.append(name)
                continue
            alias = alias_for(name)
            row = rows.setdefault(name, {
                'name': name, 'gpu': job['gpu'], 'shape': 'Provisioning',
                'ssh_alias': alias, 'ssh_command': f'ssh {alias}',
                'ssh_configured': False, 'last_execution': None,
            })
            row.update({key: job[key] for key in ('status', 'stage', 'progress')})
        if stale:
            with self.jobs_lock:
                for name in stale:
                    self.jobs.pop(name, None)
        for row in rows.values():
            row.setdefault('status', 'ready')
            row.setdefault('stage', 'Ready')
            row.setdefault('progress', 100)
        return sorted(rows.values(), key=lambda item: item['name'])

    def stop(self, name: str) -> None:
        session_manager.validate_name(name)
        with self.jobs_lock:
            job = self.jobs.pop(name, None)
        if job and job['process'].poll() is None:
            try:
                if job['process'].stdin:
                    job['process'].stdin.close()
            except (BrokenPipeError, OSError):
                pass
            job['process'].terminate()
        session_manager.stop(self.cli, name)

    def confirm_drive(self, name: str) -> None:
        session_manager.validate_name(name)
        with self.jobs_lock:
            job = self.jobs.get(name)
            if not job or not job['mount_drive']:
                raise ValueError('Drive authorization is not pending for this session')
            if job['confirmed']:
                return
            if job['process'].poll() is not None:
                raise ValueError('Provisioning process has already finished')
            job['process'].stdin.write(b'\n')
            job['process'].stdin.flush()
            job['process'].stdin.close()
            job['confirmed'] = True

    # Remote job management methods
    def session_metrics(self, session: str) -> Dict[str, Any]:
        session_manager.validate_name(session)
        from colab_session.metrics.collector import get_session_metrics
        return get_session_metrics(self.cli, session)

    def run_job(self, session: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        command = payload.get("command", "")
        detached = bool(payload.get("detached", True))
        cwd = payload.get("cwd", "/content") or "/content"
        script = payload.get("script")
        sync_dir = payload.get("sync_dir")
        download_files = payload.get("download_files")
        download_dir = payload.get("download_dir")
        env = dict(payload.get("env") or {})
        setup_command = payload.get("setup_command")
        vram = payload.get("vram")
        timeout = payload.get("timeout")

        tracking = payload.get("tracking")
        if tracking:
            from colab_session.tracking.injector import TrackingEnvironmentInjector
            track_env, track_setup = TrackingEnvironmentInjector.prepare(tracking)
            env.update(track_env)
            if track_setup:
                setup_command = f"{track_setup} && {setup_command}" if setup_command else track_setup

        result = self.job_manager.run(
            session=session,
            command=command,
            script_path=script,
            sync_dir=sync_dir,
            detached=detached,
            cwd=cwd,
            capture_output=True,
            download_files=download_files,
            download_dir=download_dir,
            env=env,
            setup_command=setup_command,
            vram=vram,
            timeout=timeout,
        )
        if detached:
            return result.to_dict()
        else:
            exit_code, output = result
            return {"exit_code": exit_code, "output": output}

    def get_job_status(self, session: str, job_id: str) -> Dict[str, Any]:
        return self.job_manager.status(session, job_id).to_dict()

    def get_job_logs(self, session: str, job_id: str, tail: int = 200) -> Dict[str, Any]:
        return {"logs": self.job_manager.logs(session, job_id, tail=tail)}

    def stop_remote_job(self, session: str, job_id: str) -> Dict[str, Any]:
        success = self.job_manager.stop(session, job_id)
        return {"stopped": success, "job_id": job_id}

    def list_remote_jobs(self, session: str) -> List[Dict[str, Any]]:
        return self.job_manager.list(session)

    def inspect_tree(
        self,
        session: str,
        path: str = "/content",
        max_depth: int = 2,
        max_items: int = 10,
        show_hidden: bool = False,
    ) -> Dict[str, Any]:
        session_manager.validate_name(session)
        return self.job_manager.tree(
            session=session,
            path=path,
            max_depth=max_depth,
            max_items=max_items,
            show_hidden=show_hidden,
        )


def handler_for(app: App):
    """Creates a request handler class binding to the provided App instance."""
    class Handler(BaseHTTPRequestHandler):
        def reply(self, value: Any, status: int = 200) -> None:
            data = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def body(self) -> Dict[str, Any]:
            length = int(self.headers.get('Content-Length', '0'))
            return json.loads(self.rfile.read(length) or b'{}')

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            try:
                if path == '/':
                    data = get_dashboard_html().encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                elif path == '/api/sessions':
                    self.reply({'sessions': app.dashboard_sessions()})
                elif re.fullmatch(r'/api/sessions/[^/]+/url', path):
                    session_name = unquote(path.split('/')[3])
                    self.reply({'url': session_manager.notebook_url(app.cli, session_name)})
                elif re.fullmatch(r'/api/sessions/[^/]+/metrics', path):
                    session_name = unquote(path.split('/')[3])
                    self.reply(app.session_metrics(session_name))
                elif re.fullmatch(r'/api/jobs/[^/]+', path):
                    job_name = unquote(path.split('/')[3])
                    self.reply(app.job_status(job_name))
                # New remote jobs GET endpoints
                elif re.fullmatch(r'/api/sessions/[^/]+/jobs', path):
                    session_name = unquote(path.split('/')[3])
                    self.reply({'jobs': app.list_remote_jobs(session_name)})
                elif re.fullmatch(r'/api/sessions/[^/]+/tree', path):
                    parsed_url = urlparse(self.path)
                    session_name = unquote(path.split('/')[3])
                    query = parse_qs(parsed_url.query)
                    remote_path = query.get('path', ['/content'])[0]
                    max_depth = int(query.get('depth', ['2'])[0])
                    max_items = min(10, int(query.get('limit', ['10'])[0]))
                    show_hidden = query.get('hidden', ['0'])[0].lower() in ('1', 'true', 'yes')
                    tree_data = app.inspect_tree(
                        session=session_name,
                        path=remote_path,
                        max_depth=max_depth,
                        max_items=max_items,
                        show_hidden=show_hidden,
                    )
                    from colab_session.session.explorer import RemoteDirectoryExplorer
                    rendered = RemoteDirectoryExplorer.render_tree(tree_data)
                    self.reply({
                        'session': session_name,
                        'path': remote_path,
                        'tree': tree_data,
                        'rendered': rendered,
                    })
                elif re.fullmatch(r'/api/sessions/[^/]+/jobs/[^/]+/logs', path):
                    parts = path.split('/')
                    session_name = unquote(parts[3])
                    job_id = unquote(parts[5])
                    self.reply(app.get_job_logs(session_name, job_id))
                elif re.fullmatch(r'/api/sessions/[^/]+/jobs/[^/]+', path):
                    parts = path.split('/')
                    session_name = unquote(parts[3])
                    job_id = unquote(parts[5])
                    self.reply(app.get_job_status(session_name, job_id))
                else:
                    self.reply({'error': 'Not found'}, 404)
            except Exception as exc:
                self.reply({'error': str(exc)}, 400)

        def validate_origin(self) -> bool:
            origin = self.headers.get('Origin')
            if origin:
                parsed = urlparse(origin)
                if parsed.hostname not in ('127.0.0.1', 'localhost', '0.0.0.0'):
                    self.reply({'error': 'Cross-origin request forbidden'}, 403)
                    return False
            return True

        def do_POST(self) -> None:
            if not self.validate_origin():
                return
            path = urlparse(self.path).path
            try:
                if path == '/api/sessions':
                    self.reply({'session': app.create(self.body())}, 202)
                elif path == '/api/reconcile':
                    self.reply({'removed': [str(p) for p in session_manager.reconcile(cli=app.cli)]})
                elif re.fullmatch(r'/api/jobs/[^/]+/drive-confirm', path):
                    name = unquote(path.split('/')[3])
                    app.confirm_drive(name)
                    self.reply({'confirmed': name})
                elif re.fullmatch(r'/api/sessions/[^/]+/backup', path):
                    name = unquote(path.split('/')[3])
                    self.reply(app.backup(name))
                # New remote job submit endpoint
                elif re.fullmatch(r'/api/sessions/[^/]+/jobs', path):
                    name = unquote(path.split('/')[3])
                    self.reply(app.run_job(name, self.body()))
                else:
                    self.reply({'error': 'Not found'}, 404)
            except Exception as exc:
                self.reply({'error': str(exc)}, 400)

        def do_DELETE(self) -> None:
            if not self.validate_origin():
                return
            path = urlparse(self.path).path
            try:
                # Stop remote job
                if re.fullmatch(r'/api/sessions/[^/]+/jobs/[^/]+', path):
                    parts = path.split('/')
                    session_name = unquote(parts[3])
                    job_id = unquote(parts[5])
                    self.reply(app.stop_remote_job(session_name, job_id))
                    return

                match = re.fullmatch(r'/api/sessions/([^/]+)', path)
                if not match:
                    return self.reply({'error': 'Not found'}, 404)
                name = unquote(match.group(1))
                app.stop(name)
                self.reply({'stopped': name})
            except Exception as exc:
                self.reply({'error': str(exc)}, 400)

        def log_message(self, *args: Any) -> None:
            pass

    return Handler


def serve(host: str = '127.0.0.1', port: int = 6767, interval: int = 30) -> None:
    cli = find_colab_cli()
    if not cli:
        raise RuntimeError('Colab CLI missing. Install with: uv tool install -e .')
    app = App(cli)
    server = ThreadingHTTPServer((host, port), handler_for(app))

    def monitor():
        while True:
            try:
                session_manager.reconcile(cli=app.cli)
            except Exception:
                pass
            if threading.Event().wait(interval):
                return

    threading.Thread(target=monitor, daemon=True).start()
    print(f'Colab SSH dashboard: http://{host}:{port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv=None) -> None:
    default_host = os.environ.get('COLAB_SSH_HOST', '127.0.0.1')
    default_port = int(os.environ.get('COLAB_SSH_PORT', '6767'))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default=default_host)
    parser.add_argument('--port', type=int, default=default_port)
    args = parser.parse_args(argv)
    serve(args.host, args.port)


if __name__ == '__main__':
    main()

