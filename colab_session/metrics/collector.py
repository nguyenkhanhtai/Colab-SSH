"""Collect and format remote session resource metrics (GPU, CPU, RAM, VRAM Quota)."""
import json
from pathlib import Path
import subprocess
from typing import Any, Dict, Optional

from colab_session.storage.backup import ssh_command_for_session

PROBE_SCRIPT = r"""python3 -c "
import json, os, subprocess

res = {}
try:
    out = subprocess.run(['nvidia-smi', '--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu', '--format=csv,noheader,nounits'], capture_output=True, text=True, check=True).stdout.strip()
    if out:
        parts = [p.strip() for p in out.splitlines()[0].split(',')]
        res['gpu'] = {
            'name': parts[0],
            'util_pct': int(parts[1]) if parts[1].isdigit() else 0,
            'memory_used_mb': int(parts[2]) if parts[2].isdigit() else 0,
            'memory_total_mb': int(parts[3]) if parts[3].isdigit() else 0,
            'temperature_c': int(parts[4]) if parts[4].isdigit() else 0,
        }
except Exception:
    res['gpu'] = None

try:
    load = os.getloadavg()
    res['cpu'] = {'load_1m': round(load[0], 2), 'load_5m': round(load[1], 2), 'load_15m': round(load[2], 2)}
except Exception:
    res['cpu'] = None

try:
    mem = {}
    with open('/proc/meminfo') as f:
        for line in f:
            p = line.split(':')
            if len(p) == 2:
                mem[p[0].strip()] = int(p[1].split()[0]) // 1024
    total_mb = mem.get('MemTotal', 0)
    avail_mb = mem.get('MemAvailable', 0)
    res['ram'] = {'total_mb': total_mb, 'available_mb': avail_mb, 'used_mb': max(0, total_mb - avail_mb)}
except Exception:
    res['ram'] = None

try:
    q_path = '/root/.colab-jobs/quota.json'
    if os.path.exists(q_path):
        with open(q_path) as f:
            res['quota'] = json.load(f)
    else:
        res['quota'] = None
except Exception:
    res['quota'] = None

print('---METRICS---')
print(json.dumps(res))
"
"""


def get_session_metrics(cli: str, session: str, timeout: int = 10) -> Dict[str, Any]:
    """Query remote session resource metrics via SSH."""
    ssh = ssh_command_for_session(cli, session)
    try:
        proc = subprocess.run([*ssh, PROBE_SCRIPT], capture_output=True, text=True, timeout=timeout)
        _, _, json_part = proc.stdout.partition("---METRICS---")
        if json_part.strip():
            data = json.loads(json_part.strip())
            data["session"] = session
            return data
    except Exception as exc:
        return {"session": session, "error": str(exc)}
    return {"session": session, "error": "No metrics output returned from remote host."}


def format_metrics_table(metrics: Dict[str, Any]) -> str:
    """Format metrics dictionary into a readable CLI report."""
    sess = metrics.get("session", "unknown")
    if "error" in metrics:
        return f"Session: {sess}\n  • Status: Unreachable ({metrics['error']})"

    lines = [
        "╔════════════════════════════════════════════════════════════════════════════╗",
        f"║                     SESSION METRICS: {sess.ljust(41)} ║",
        "╚════════════════════════════════════════════════════════════════════════════╝",
    ]

    gpu = metrics.get("gpu")
    if gpu:
        used = gpu.get("memory_used_mb", 0)
        tot = gpu.get("memory_total_mb", 1)
        pct = (used / tot) * 100 if tot else 0
        lines.append(f"  • GPU Accelerator: {gpu.get('name', 'N/A')}")
        lines.append(f"    - Compute Load : {gpu.get('util_pct', 0)}% utilization")
        lines.append(f"    - VRAM Usage   : {used:,} MB / {tot:,} MB ({pct:.1f}%)")
        lines.append(f"    - Temperature  : {gpu.get('temperature_c', 0)}°C")
    else:
        lines.append("  • GPU Accelerator: None / Offline")

    cpu = metrics.get("cpu")
    if cpu:
        lines.append(f"  • CPU Load       : {cpu.get('load_1m', 0)} (1m), {cpu.get('load_5m', 0)} (5m)")

    ram = metrics.get("ram")
    if ram:
        r_used = ram.get("used_mb", 0)
        r_tot = ram.get("total_mb", 1)
        r_pct = (r_used / r_tot) * 100 if r_tot else 0
        lines.append(f"  • System RAM     : {r_used:,} MB / {r_tot:,} MB ({r_pct:.1f}% used)")

    quota = metrics.get("quota")
    lines.append("")
    lines.append("[Resource Ledger & VRAM Quotas]")
    if quota and isinstance(quota, dict):
        q_tot = quota.get("total_vram_mb", 0)
        q_alloc = quota.get("allocated_vram_mb", 0)
        q_avail = quota.get("available_vram_mb", q_tot - q_alloc)
        lines.append(f"  • Total VRAM     : {q_tot:,} MB")
        lines.append(f"  • Allocated VRAM : {q_alloc:,} MB")
        lines.append(f"  • Available VRAM : {q_avail:,} MB (Headroom for new jobs)")
        allocs = quota.get("allocations", {})
        if allocs:
            lines.append("  • Active Job Quotas:")
            for j_id, info in allocs.items():
                mb = info.get("vram_mb", 0)
                pid = info.get("pid", 0)
                lines.append(f"    - {j_id}: {mb:,} MB (PID: {pid})")
        else:
            lines.append("  • Active Job Quotas: 0 jobs currently allocated")
    else:
        tot_vram = gpu.get("memory_total_mb", 15360) if gpu else 15360
        lines.append(f"  • Available VRAM : {tot_vram:,} MB (100% available, no active quotas)")

    lines.append("═" * 78)
    return "\n".join(lines)
