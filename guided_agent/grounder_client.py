"""Client for the Modal GoClick grounder. One kept-alive HTTPS connection, IPv4 forced."""
from __future__ import annotations

import base64
import io
import os
import time
from pathlib import Path

import ipv4_only  # noqa: F401  (must come before httpx opens sockets)
import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parent
URL = os.environ.get("GROUNDER_URL",
                     "https://projects-tarun97--guided-cua-goclick-grounder-ground.us-east.modal.run")
TOKEN = (ROOT / ".grounder_token").read_text().strip()

_client = httpx.Client(timeout=httpx.Timeout(300, connect=20), http2=False, follow_redirects=True)


def jpeg_b64(png_or_img, quality: int = 85) -> str:
    img = png_or_img if isinstance(png_or_img, Image.Image) else Image.open(io.BytesIO(png_or_img))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def ground(image, targets: list[str], mode: str = "description") -> dict:
    """image: PNG bytes or PIL image. Returns the server JSON plus round-trip time."""
    payload = {"token": TOKEN, "image_b64": jpeg_b64(image), "targets": targets, "mode": mode}
    t0 = time.time()
    r = _client.post(URL, json=payload)
    r.raise_for_status()
    data = r.json()
    data["rtt_ms"] = round((time.time() - t0) * 1000, 1)
    data["network_ms"] = round(data["rtt_ms"] - data["gpu_ms"] - data["decode_ms"], 1)
    return data


def warm() -> dict:
    """Wake the GPU container (tiny image, one target) so the first real call is warm."""
    from PIL import Image as _I
    return ground(_I.new("RGB", (64, 64), "white"), ["the button"])
