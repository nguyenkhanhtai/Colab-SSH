"""Resource loader for external templates, HTML dashboards, and remote execution scripts."""
from pathlib import Path
from typing import Any, Dict, Optional

PACKAGE_DIR = Path(__file__).resolve().parent


def get_resource_path(*parts: str) -> Path:
    """Resolve an absolute path to a package resource file."""
    path = PACKAGE_DIR.joinpath(*parts)
    if not path.is_file():
        raise FileNotFoundError(f"Colab SSH resource not found: {path}")
    return path


def read_resource(*parts: str) -> str:
    """Read and return content of a package resource file as string."""
    return get_resource_path(*parts).read_text(encoding="utf-8")


def render_template(*parts: str, context: Optional[Dict[str, Any]] = None) -> str:
    """Read a template file and substitute placeholder keys like {{KEY}}."""
    content = read_resource(*parts)
    if context:
        for key, val in context.items():
            content = content.replace(f"{{{{{key}}}}}", str(val))
    return content

