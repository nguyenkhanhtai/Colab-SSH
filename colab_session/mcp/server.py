"""Model Context Protocol (MCP) stdio server allowing AI assistants to control Colab."""
import io
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Callable, Dict, List, Optional

from colab_session.session.manager import find_colab_cli
from colab_session.jobs.config import JobConfig, JobConfigDispatcher
from colab_session.jobs.manager import JobManager
from colab_session.jobs.models import format_job_manifest, resolve_log_file, validate_job_requirements
from colab_session.session.manager import sessions as list_sessions, stop as stop_session
from colab_session.session.resolver import SessionResolver
from colab_session.storage.backup import backup as backup_session

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[MCP] %(message)s")


class ColabMCPServer:
    """Zero-dependency standard Model Context Protocol (MCP) server over stdio."""

    def __init__(self, cli: Optional[str] = None):
        self.cli = cli or find_colab_cli() or "colab"
        self.resolver = SessionResolver(self.cli)
        self.job_manager = JobManager(self.cli)
        self.dispatcher = JobConfigDispatcher(self.cli)

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "colab_list_sessions",
                "description": "List all active Google Colab GPU sessions with their status, accelerator type, and SSH command.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "colab_resolve_session",
                "description": "Find an existing active session matching requested GPU (T4, L4, G4, A100, H100), or automatically provision a new one if not running.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "gpu": {
                            "type": "string",
                            "description": "Required accelerator: T4, L4, G4, A100, H100 (default: T4)",
                            "default": "T4"
                        },
                        "auto_create": {
                            "type": "boolean",
                            "description": "Whether to provision a new server if matching GPU is not running",
                            "default": True
                        },
                        "session_name": {
                            "type": "string",
                            "description": "Optional custom name if a new session needs to be created"
                        }
                    }
                }
            },
            {
                "name": "colab_run_job",
                "description": "Run a command or script on a Colab GPU server. Explicitly declares and validates execution requirements (session/GPU, script or command, working directory, log path, artifacts) via execution manifest. If session is omitted, auto-matches or creates a session with the specified GPU.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to execute on remote Colab VM (e.g. 'nvidia-smi', 'python3 train.py'). Required if script_path is omitted."
                        },
                        "gpu": {
                            "type": "string",
                            "description": "GPU to target if session is omitted (default: T4)",
                            "default": "T4"
                        },
                        "session": {
                            "type": "string",
                            "description": "Specific session name (optional; auto-resolved if omitted)"
                        },
                        "script_path": {
                            "type": "string",
                            "description": "Path to local script on this machine to upload and execute on Colab"
                        },
                        "sync_dir": {
                            "type": "string",
                            "description": "Path to local directory on this machine to sync to Colab before execution"
                        },
                        "cwd": {
                            "type": "string",
                            "description": "Working directory on the remote Colab VM (default: /content)",
                            "default": "/content"
                        },
                        "detached": {
                            "type": "boolean",
                            "description": "True to run in background (returns job ID); False to wait and stream output (default: False)",
                            "default": False
                        },
                        "download_files": {
                            "type": "array",
                            "items": { "type": "string" },
                            "description": "Remote files/patterns to download to local machine upon job completion"
                        },
                        "download_dir": {
                            "type": "string",
                            "description": "Local destination directory for downloaded files (default: ./downloads)",
                            "default": "./downloads"
                        },
                        "log_file": {
                            "type": "string",
                            "description": "Path to local log destination (default: logs/<session>/<date>/<job_id>.log)"
                        }
                    }
                }
            },
            {
                "name": "colab_run_from_config",
                "description": "Execute a job defined in a declarative configuration file (e.g. colab-job.json), auto-reusing or provisioning the GPU session.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "config_path": {
                            "type": "string",
                            "description": "Path to job JSON config file (default: ./colab-job.json)",
                            "default": "colab-job.json"
                        }
                    }
                }
            },
            {
                "name": "colab_get_job_status",
                "description": "Check current execution status, exit code, and timestamps of a remote job.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session": { "type": "string", "description": "Session name where the job is running" },
                        "job_id": { "type": "string", "description": "Job identifier (e.g. job-a1b2c3d4)" }
                    },
                    "required": ["session", "job_id"]
                }
            },
            {
                "name": "colab_get_job_logs",
                "description": "Fetch stdout/stderr logs of a running or completed remote job.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session": { "type": "string", "description": "Session name" },
                        "job_id": { "type": "string", "description": "Job identifier" },
                        "tail": { "type": "integer", "description": "Number of lines to read from log tail", "default": 200 }
                    },
                    "required": ["session", "job_id"]
                }
            },
            {
                "name": "colab_stop_job",
                "description": "Terminate a running remote job process on Colab.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session": { "type": "string", "description": "Session name" },
                        "job_id": { "type": "string", "description": "Job identifier to stop" }
                    },
                    "required": ["session", "job_id"]
                }
            },
            {
                "name": "colab_backup_session",
                "description": "Backup workspace of a Colab session to Google Drive and return the backup key.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session": { "type": "string", "description": "Session name to backup" }
                    },
                    "required": ["session"]
                }
            },
            {
                "name": "colab_stop_session",
                "description": "Stop and delete a Colab VM session and clean up SSH state.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session": { "type": "string", "description": "Session name to stop" }
                    },
                    "required": ["session"]
                }
            },
            {
                "name": "colab_download_files",
                "description": "Download specific files, directories, or glob patterns from a Colab session to a local directory.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session": { "type": "string", "description": "Target Colab session name" },
                        "files": {
                            "type": "array",
                            "items": { "type": "string" },
                            "description": "Remote files, directories, or glob patterns to download (e.g. ['model.pt', 'results/*.png'])"
                        },
                        "dest_dir": {
                            "type": "string",
                            "description": "Local directory to save files (default: ./downloads)",
                            "default": "./downloads"
                        },
                        "cwd": {
                            "type": "string",
                            "description": "Base directory on remote Colab VM (default: /content)",
                            "default": "/content"
                        }
                    },
                    "required": ["session", "files"]
                }
            },
            {
                "name": "colab_pull_job_artifacts",
                "description": "Download the output artifacts configured in a remote job's download_files specification.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session": { "type": "string", "description": "Session name where the job ran" },
                        "job_id": { "type": "string", "description": "Job ID" },
                        "dest_dir": {
                            "type": "string",
                            "description": "Optional local directory override (uses job config download_dir if omitted)"
                        }
                    },
                    "required": ["session", "job_id"]
                }
            },
            {
                "name": "colab_tree_directory",
                "description": "Explore and observe the remote directory tree and file paths on a Colab session via SSH. Limits each directory branch to at most 10 items to prevent context bloat.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session": {
                            "type": "string",
                            "description": "Session name (optional; if omitted, automatically targets the first active session)"
                        },
                        "path": {
                            "type": "string",
                            "description": "Remote directory path to inspect on Colab (default: /content)",
                            "default": "/content"
                        },
                        "max_depth": {
                            "type": "integer",
                            "description": "Maximum tree depth to traverse (default: 2)",
                            "default": 2
                        },
                        "max_items_per_branch": {
                            "type": "integer",
                            "description": "Maximum items to show per directory branch (default: 10, max: 10)",
                            "default": 10
                        },
                        "show_hidden": {
                            "type": "boolean",
                            "description": "Whether to include hidden files/directories (starting with .)",
                            "default": False
                        }
                    }
                }
            }
        ]

    def call_tool(self, name: str, args: Dict[str, Any]) -> str:
        """Dispatch a tool call and return a text response."""
        if name == "colab_list_sessions":
            sessions = list_sessions(cli=self.cli)
            return json.dumps(sessions, indent=2)

        elif name == "colab_resolve_session":
            gpu = args.get("gpu", "T4")
            auto_create = bool(args.get("auto_create", True))
            sess_name = args.get("session_name")
            session, was_created = self.resolver.resolve_or_create(
                gpu=gpu,
                session_name=sess_name,
                auto_create=auto_create,
            )
            return json.dumps({
                "session": session,
                "gpu": gpu,
                "was_created": was_created,
                "status": "ready"
            }, indent=2)

        elif name == "colab_run_job":
            session = args.get("session")
            gpu = args.get("gpu", "T4")
            if not session:
                session, _ = self.resolver.resolve_or_create(gpu=gpu)

            command = args.get("command", "")
            script_path = args.get("script_path")
            sync_dir = args.get("sync_dir")
            cwd = args.get("cwd", "/content") or "/content"
            detached = bool(args.get("detached", False))
            download_files = args.get("download_files")
            download_dir = args.get("download_dir")
            log_file = args.get("log_file")

            validate_job_requirements(
                command=command,
                script_path=script_path,
                sync_dir=sync_dir,
                session=session,
            )

            manifest = format_job_manifest(
                session=session,
                command=command,
                script_path=script_path,
                sync_dir=sync_dir,
                cwd=cwd,
                detached=detached,
                download_files=download_files,
                download_dir=download_dir,
                log_file=log_file,
                gpu=gpu,
            )

            result = self.job_manager.run(
                session=session,
                command=command,
                script_path=script_path,
                sync_dir=sync_dir,
                cwd=cwd,
                detached=detached,
                capture_output=True,
                download_files=download_files,
                download_dir=download_dir,
                log_file=log_file,
            )
            if detached:
                return json.dumps({
                    "manifest": manifest,
                    **result.to_dict()
                }, indent=2)
            else:
                exit_code, output = result
                return json.dumps({
                    "manifest": manifest,
                    "session": session,
                    "command": command or f"python3 {Path(script_path).name}",
                    "exit_code": exit_code,
                    "output": output,
                    "log_file": str(resolve_log_file(session, log_file)),
                }, indent=2)

        elif name == "colab_run_from_config":
            config_path = args.get("config_path", "colab-job.json")
            cfg = JobConfig.load(config_path)
            session, was_created, result = self.dispatcher.dispatch(cfg)
            manifest = format_job_manifest(
                session=session,
                command=cfg.command,
                script_path=cfg.script,
                sync_dir=cfg.sync_dir,
                cwd=cfg.cwd,
                detached=cfg.detached,
                download_files=cfg.download_files,
                download_dir=cfg.download_dir,
                log_file=cfg.log_file,
                gpu=cfg.gpu,
                env=cfg.env,
                setup_command=cfg.setup_command,
                tracking=cfg.tracking,
            )
            res_dict = result.to_dict() if hasattr(result, "to_dict") else {"result": result}
            return json.dumps({
                "manifest": manifest,
                "session": session,
                "was_created": was_created,
                **res_dict
            }, indent=2)

        elif name == "colab_get_job_status":
            session = args["session"]
            job_id = args["job_id"]
            status = self.job_manager.status(session, job_id)
            return json.dumps(status.to_dict(), indent=2)

        elif name == "colab_get_job_logs":
            session = args["session"]
            job_id = args["job_id"]
            tail = int(args.get("tail", 200))
            logs = self.job_manager.logs(session, job_id, tail=tail)
            return logs

        elif name == "colab_stop_job":
            session = args["session"]
            job_id = args["job_id"]
            stopped = self.job_manager.stop(session, job_id)
            return json.dumps({"stopped": stopped, "job_id": job_id}, indent=2)

        elif name == "colab_backup_session":
            session = args["session"]
            res = backup_session(self.cli, session)
            return json.dumps(res, indent=2)

        elif name == "colab_stop_session":
            session = args["session"]
            stop_session(self.cli, session)
            return json.dumps({"status": "stopped", "session": session}, indent=2)

        elif name == "colab_download_files":
            session = args["session"]
            files = args["files"]
            dest_dir = args.get("dest_dir", "./downloads") or "./downloads"
            cwd = args.get("cwd", "/content") or "/content"
            downloaded = self.job_manager.download_files(session, files, local_dest_dir=dest_dir, remote_cwd=cwd)
            return json.dumps({
                "session": session,
                "dest_dir": dest_dir,
                "downloaded_files": downloaded,
                "count": len(downloaded),
            }, indent=2)

        elif name == "colab_pull_job_artifacts":
            session = args["session"]
            job_id = args["job_id"]
            dest_dir = args.get("dest_dir")
            downloaded = self.job_manager.pull(session, job_id, local_dest_dir=dest_dir)
            return json.dumps({
                "session": session,
                "job_id": job_id,
                "downloaded_artifacts": downloaded,
                "count": len(downloaded),
            }, indent=2)

        elif name == "colab_tree_directory":
            session = args.get("session")
            if not session:
                active = list_sessions(cli=self.cli)
                if not active:
                    return "Error: No active Colab sessions found."
                session = active[0]["name"]
            path = args.get("path", "/content") or "/content"
            max_depth = int(args.get("max_depth", 2))
            # Strict cap at 10 items per branch as requested by user
            max_items = min(10, int(args.get("max_items_per_branch", 10)))
            show_hidden = bool(args.get("show_hidden", False))

            tree_data = self.job_manager.tree(
                session=session,
                path=path,
                max_depth=max_depth,
                max_items=max_items,
                show_hidden=show_hidden,
            )
            from colab_session.session.explorer import RemoteDirectoryExplorer
            rendered = RemoteDirectoryExplorer.render_tree(tree_data)
            return f"Directory Tree on session '{session}' (capped at {max_items} items/branch):\n\n{rendered}"

        else:
            raise ValueError(f"Unknown tool name: {name}")

    def handle_request(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = req.get("method")
        msg_id = req.get("id")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "colab-ssh-mcp",
                        "version": "0.2.0"
                    }
                }
            }

        elif method in ("notifications/initialized", "initialized"):
            return None

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": self.get_tool_definitions()
                }
            }

        elif method == "tools/call":
            params = req.get("params", {})
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            try:
                text_out = self.call_tool(tool_name, tool_args)
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": text_out}
                        ]
                    }
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "isError": True,
                        "content": [
                            {"type": "text", "text": f"Error executing tool '{tool_name}': {str(exc)}"}
                        ]
                    }
                }

        elif method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

        else:
            if msg_id is not None:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method '{method}' not found"
                    }
                }
            return None

    def serve_stdio(self) -> None:
        """Run the JSON-RPC loop over standard input and output."""
        logging.info("Starting Colab MCP Server over stdio...")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                resp = self.handle_request(req)
                if resp is not None:
                    out = json.dumps(resp) + "\n"
                    sys.stdout.write(out)
                    sys.stdout.flush()
            except Exception as exc:
                logging.error(f"Error handling request: {exc}")


def main():
    server = ColabMCPServer()
    server.serve_stdio()


if __name__ == "__main__":
    main()

