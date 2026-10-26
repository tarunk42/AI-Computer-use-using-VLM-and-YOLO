"""Talking to the desktop container over SSH (fast, multiplexed)."""
from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KEY = ROOT / "container" / "id_ed25519"
HOST = os.environ.get("CUA_HOST", "192.168.64.13")
USER = "root"

SSH_BASE = [
    "ssh", "-i", str(KEY),
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "LogLevel=ERROR",
    "-o", "ControlMaster=auto",
    "-o", f"ControlPath=/tmp/cua-ssh-%r@%h:%p",
    "-o", "ControlPersist=180",
    f"{USER}@{HOST}",
]


def sh(cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(SSH_BASE + [cmd], capture_output=True, timeout=timeout)


def capture_png(retries: int = 3) -> tuple[bytes, float]:
    """Screenshot the container's X display, return validated PNG bytes.

    A truncated transfer used to reach the VLM as a corrupt PNG; validate and retry.
    """
    import io as _io
    from PIL import Image as _Image

    t0 = time.time()
    last_err = None
    for _ in range(retries):
        p = sh("DISPLAY=:0 scrot -o -z /tmp/f.png && base64 -w0 /tmp/f.png")
        if p.returncode != 0:
            last_err = p.stderr.decode()[:300]
            continue
        try:
            png = base64.b64decode(p.stdout)
            _Image.open(_io.BytesIO(png)).verify()
            return png, time.time() - t0
        except Exception as e:  # noqa: BLE001
            last_err = f"invalid png: {e}"
            time.sleep(0.4)
    raise RuntimeError(f"capture failed after {retries} tries: {last_err}")


def page_state() -> dict:
    """The page's own report of its form state - ground truth for scoring only."""
    p = sh("curl -s http://127.0.0.1:8080/state")
    try:
        return json.loads(p.stdout.decode() or "{}")
    except json.JSONDecodeError:
        return {}


def click(x: int, y: int) -> float:
    t0 = time.time()
    p = sh(f"DISPLAY=:0 xdotool mousemove {int(x)} {int(y)} click 1")
    if p.returncode != 0:
        raise RuntimeError(f"click failed: {p.stderr.decode()[:300]}")
    return time.time() - t0


def type_text(text: str) -> float:
    t0 = time.time()
    p = sh(f"DISPLAY=:0 xdotool type --delay 15 -- {shlex.quote(text)}")
    if p.returncode != 0:
        raise RuntimeError(f"type failed: {p.stderr.decode()[:300]}")
    return time.time() - t0


def key(combo: str) -> float:
    t0 = time.time()
    sh(f"DISPLAY=:0 xdotool key --clearmodifiers {combo}")
    return time.time() - t0


def clear_and_reload() -> None:
    """Reload the task page so each episode starts from a clean state."""
    key("ctrl+a")          # harmless outside inputs
    key("F5")
    time.sleep(2.0)


def wait_boot(timeout: int = 120) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = sh("DISPLAY=:0 xdotool getdisplaygeometry 2>/dev/null || true")
        if p.stdout.strip():
            return
        time.sleep(1.0)
    raise TimeoutError(f"desktop at {HOST} never became ready")
