"""Remote filesystem and directory tree inspector for Colab sessions."""
import json
from pathlib import Path
import shlex
import subprocess
from typing import Any, Dict, List, Optional

from colab_session.exceptions import RemoteTreeError
from colab_session.storage.backup import ssh_command_for_session


from colab_session.resources import read_resource


def get_remote_tree_script() -> str:
    """Load remote tree inspection python script from package resources."""
    return read_resource("scripts", "remote_tree.py")


_REMOTE_TREE_SCRIPT = get_remote_tree_script()


class RemoteDirectoryExplorer:
    """Inspects remote files and directories via SSH and produces visual trees."""

    def __init__(self, cli: str):
        self.cli = cli

    def _ssh_command(self, session: str) -> List[str]:
        return ssh_command_for_session(self.cli, session)

    def inspect_tree(
        self,
        session: str,
        path: str = "/content",
        max_depth: int = 2,
        max_items_per_branch: int = 10,
        show_hidden: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute remote inspection on Colab VM and return parsed directory tree structure.
        Caps entries per branch to max_items_per_branch (default: 10).
        """
        # Ensure max_items_per_branch is at least 1 and capped
        limit = max(1, min(100, max_items_per_branch))
        depth = max(1, min(10, max_depth))
        hidden_flag = "1" if show_hidden else "0"

        ssh = self._ssh_command(session)
        cmd = f"python3 - {shlex.quote(path)} {depth} {limit} {hidden_flag}"

        try:
            res = subprocess.run([*ssh, cmd], input=_REMOTE_TREE_SCRIPT, capture_output=True, text=True)
        except subprocess.SubprocessError as exc:
            raise RemoteTreeError(f"Failed to execute SSH command on session '{session}': {exc}") from exc

        if res.returncode != 0:
            err_msg = (res.stderr or "").strip() or f"Process exited with status {res.returncode}"
            if "has stopped or is missing" in err_msg or "Connection closed" in err_msg:
                raise RemoteTreeError(f"Session '{session}' is not reachable or has stopped. Please start a session first.")
            raise RemoteTreeError(f"Remote tree inspection failed on session '{session}': {err_msg}")

        raw_output = res.stdout.strip()
        try:
            return json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise RemoteTreeError(f"Failed to parse remote directory structure: {exc}\nOutput: {raw_output}") from exc

    @classmethod
    def render_tree(cls, node: Dict[str, Any]) -> str:
        """Render a JSON tree node into an ASCII/Unicode hierarchy string."""
        lines = cls._format_node(node, prefix="", is_last=True, is_root=True)
        return "\n".join(lines)

    @classmethod
    def _format_node(
        cls,
        node: Dict[str, Any],
        prefix: str = "",
        is_last: bool = True,
        is_root: bool = True,
    ) -> List[str]:
        lines = []
        name = node.get("name") or node.get("path", "")
        if is_root:
            root_display = f"{node.get('path', name)}/" if node.get("is_dir") else node.get("path", name)
            if node.get("error"):
                root_display += f" [Error: {node['error']}]"
            lines.append(root_display)
        else:
            connector = "└── " if is_last else "├── "
            if node.get("is_dir"):
                suffix = "/"
            else:
                sz = node.get("size_human", "")
                suffix = f" ({sz})" if sz else ""
            if node.get("error"):
                suffix += f" [Error: {node['error']}]"

            lines.append(f"{prefix}{connector}{name}{suffix}")
            prefix += "    " if is_last else "│   "

        children = node.get("children", [])
        has_more = node.get("has_more", False)
        rem = node.get("remaining_count", 0)

        for i, child in enumerate(children):
            child_is_last = (i == len(children) - 1) and not has_more
            lines.extend(cls._format_node(child, prefix, child_is_last, is_root=False))

        if has_more:
            lines.append(f"{prefix}└── ... (+{rem} more items)")

        return lines

