"""VRAM quota parsing, validation, and remote ledger management."""
import re
from typing import Any, Dict, Optional, Tuple


def parse_vram_to_mb(value: Optional[str | int | float]) -> Optional[int]:
    """
    Parse a VRAM request string or number into integer megabytes (MB).
    Supports: "8GB", "8gb", "8G", "8g", "8192MB", "8192M", "8192", 8192, "8.5GB".
    Returns None if value is None or empty.
    Raises ValueError if format is invalid or <= 0.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        val = int(value)
        if val <= 0:
            raise ValueError(f"VRAM quota must be positive, got {value}")
        return val

    s = str(value).strip()
    if not s:
        return None

    # Check for GB / G
    match_gb = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(?:gb|g)$", s, re.IGNORECASE)
    if match_gb:
        gb = float(match_gb.group(1))
        if gb <= 0:
            raise ValueError(f"VRAM quota must be positive, got '{value}'")
        return int(gb * 1024)

    # Check for MB / M
    match_mb = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(?:mb|m)?$", s, re.IGNORECASE)
    if match_mb:
        mb = float(match_mb.group(1))
        if mb <= 0:
            raise ValueError(f"VRAM quota must be positive, got '{value}'")
        return int(mb)

    raise ValueError(f"Invalid VRAM format '{value}'. Expected e.g. '8GB', '4G', '8192MB', or integer MB.")


def parse_timeout_to_seconds(value: Optional[str | int | float]) -> Optional[int]:
    """
    Parse a timeout string or number into integer seconds.
    Supports: "1h", "1.5h", "30m", "45s", "3600", 3600.
    Returns None if value is None or empty.
    Raises ValueError if format is invalid or <= 0.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        val = int(value)
        if val <= 0:
            raise ValueError(f"Timeout must be positive, got {value}")
        return val

    s = str(value).strip()
    if not s:
        return None

    # Hours
    match_h = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(?:h|hr|hours?)$", s, re.IGNORECASE)
    if match_h:
        h = float(match_h.group(1))
        if h <= 0:
            raise ValueError(f"Timeout must be positive, got '{value}'")
        return int(h * 3600)

    # Minutes
    match_m = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(?:m|min|minutes?)$", s, re.IGNORECASE)
    if match_m:
        m = float(match_m.group(1))
        if m <= 0:
            raise ValueError(f"Timeout must be positive, got '{value}'")
        return int(m * 60)

    # Seconds
    match_s = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(?:s|sec|seconds?)?$", s, re.IGNORECASE)
    if match_s:
        secs = float(match_s.group(1))
        if secs <= 0:
            raise ValueError(f"Timeout must be positive, got '{value}'")
        return int(secs)

    raise ValueError(f"Invalid timeout format '{value}'. Expected e.g. '1h', '30m', '3600s', or integer seconds.")


def check_session_vram_capacity(cli: str, session: str, requested_mb: int) -> Tuple[bool, int, int]:
    """
    Check if a remote session has enough available VRAM for the requested quota.
    Returns (has_capacity, available_mb, total_mb).
    """
    from colab_session.storage.backup import ssh_command_for_session
    import json
    import subprocess

    ssh = ssh_command_for_session(cli, session)
    # Check remote quota status or fallback to nvidia-smi
    probe_cmd = (
        "if [ -f /root/.colab-jobs/remote_quota_manager.py ]; then "
        "  python3 /root/.colab-jobs/remote_quota_manager.py status 2>/dev/null; "
        "else "
        "  tot=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -n1 || echo 15360); "
        "  echo '{\"total_vram_mb\": '$tot', \"allocated_vram_mb\": 0, \"available_vram_mb\": '$tot'}'; "
        "fi"
    )
    try:
        res = subprocess.run([*ssh, probe_cmd], capture_output=True, text=True, timeout=10)
        lines = [ln.strip() for ln in res.stdout.strip().splitlines() if ln.strip().startswith("{")]
        if lines:
            data = json.loads(lines[-1])
            total = int(data.get("total_vram_mb", 15360))
            available = int(data.get("available_vram_mb", total))
            return (available >= requested_mb, available, total)
    except Exception:
        pass
    # If probe fails, default optimistic check against standard 15360MB
    return (15360 >= requested_mb, 15360, 15360)

