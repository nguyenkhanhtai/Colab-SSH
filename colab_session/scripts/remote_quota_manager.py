#!/usr/bin/env python3
"""Atomic VRAM Quota Ledger Manager running on remote Colab instances."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

JOBS_DIR = Path("/root/.colab-jobs")
LEDGER_PATH = JOBS_DIR / "quota.json"
LOCK_PATH = JOBS_DIR / "quota.lock"


def get_gpu_total_vram_mb() -> int:
    """Query total GPU memory using nvidia-smi."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        if lines:
            return int(float(lines[0]))
    except Exception:
        pass
    return 15360  # Default fallback if query fails (T4 standard)


def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def load_and_prune_ledger(total_vram: int) -> dict:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "total_vram_mb": total_vram,
        "allocations": {},
    }
    if LEDGER_PATH.exists():
        try:
            loaded = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and "allocations" in loaded:
                data["allocations"] = loaded.get("allocations", {})
        except Exception:
            pass

    # Prune dead jobs
    pruned = {}
    for j_id, item in data["allocations"].items():
        pid = item.get("pid")
        status_file = JOBS_DIR / f"{j_id}.status"
        # If status says EXIT or TIMED_OUT or PID dead, don't keep reservation
        is_exited = False
        if status_file.exists():
            text = status_file.read_text(errors="ignore")
            if "EXIT " in text or "TIMED_OUT" in text:
                is_exited = True
        if not is_exited and pid and is_pid_alive(pid):
            pruned[j_id] = item
        elif not is_exited and not pid:
            # Check if job meta was created in the last 15 seconds (startup grace period)
            age = time.time() - item.get("timestamp", 0)
            if age < 30:
                pruned[j_id] = item

    data["allocations"] = pruned
    data["total_vram_mb"] = total_vram
    allocated = sum(it.get("vram_mb", 0) for it in pruned.values())
    data["allocated_vram_mb"] = allocated
    data["available_vram_mb"] = max(0, total_vram - allocated)
    return data


def save_ledger(data: dict) -> None:
    allocated = sum(it.get("vram_mb", 0) for it in data["allocations"].values())
    data["allocated_vram_mb"] = allocated
    data["available_vram_mb"] = max(0, data["total_vram_mb"] - allocated)
    LEDGER_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def reserve(job_id: str, vram_mb: int, pid: int = 0) -> int:
    total_vram = get_gpu_total_vram_mb()
    with open(LOCK_PATH, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            data = load_and_prune_ledger(total_vram)
            available = data["available_vram_mb"]
            if available < vram_mb:
                res = {
                    "status": "rejected",
                    "reason": "insufficient_vram",
                    "job_id": job_id,
                    "requested_mb": vram_mb,
                    "available_mb": available,
                    "total_mb": total_vram,
                    "allocated_mb": data["allocated_vram_mb"],
                }
                print(json.dumps(res))
                return 1

            data["allocations"][job_id] = {
                "vram_mb": vram_mb,
                "pid": pid,
                "timestamp": time.time(),
            }
            save_ledger(data)
            res = {
                "status": "reserved",
                "job_id": job_id,
                "requested_mb": vram_mb,
                "available_mb": data["available_vram_mb"],
                "total_mb": total_vram,
                "allocated_mb": data["allocated_vram_mb"],
            }
            print(json.dumps(res))
            return 0
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def release(job_id: str) -> int:
    total_vram = get_gpu_total_vram_mb()
    with open(LOCK_PATH, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            data = load_and_prune_ledger(total_vram)
            data["allocations"].pop(job_id, None)
            save_ledger(data)
            print(json.dumps({"status": "released", "job_id": job_id, "available_mb": data["available_vram_mb"]}))
            return 0
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def status() -> int:
    total_vram = get_gpu_total_vram_mb()
    with open(LOCK_PATH, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            data = load_and_prune_ledger(total_vram)
            save_ledger(data)
            print(json.dumps(data))
            return 0
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: remote_quota_manager.py [reserve <job_id> <vram_mb> [pid] | release <job_id> | status]")
    cmd = sys.argv[1].lower()
    if cmd == "reserve":
        if len(sys.argv) < 4:
            sys.exit("reserve requires <job_id> <vram_mb>")
        job_id = sys.argv[2]
        vram_mb = int(sys.argv[3])
        pid = int(sys.argv[4]) if len(sys.argv) > 4 else 0
        sys.exit(reserve(job_id, vram_mb, pid))
    elif cmd == "release":
        if len(sys.argv) < 3:
            sys.exit("release requires <job_id>")
        sys.exit(release(sys.argv[2]))
    elif cmd == "status":
        sys.exit(status())
    else:
        sys.exit(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
