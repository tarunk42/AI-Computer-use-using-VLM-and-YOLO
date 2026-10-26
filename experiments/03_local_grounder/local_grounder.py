#!/usr/bin/env python3
"""Local stand-in for the Modal grounder - identical HTTP contract.

Modal's control plane was unreachable when this was built, so the GoClick service runs
here instead. Swapping back is a one-line URL change in agent.py / the web demo.

POST /ground {"image_b64", "prompt", "mode", "token"} -> {"ok","point","loc",...}
GET  /health -> {"ok": true, "model": ...}
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoModelForCausalLM, AutoProcessor

MODEL_ID = "HongxinLi/GoClick-Base"
# Apple GPU when present: ~2.5x faster warm than CPU (see REPORT.md).
DEVICE = os.environ.get("GROUNDER_DEVICE") or (
    "mps" if torch.backends.mps.is_available() else "cpu")
if DEVICE == "mps":
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
PORT = int(os.environ.get("GROUNDER_PORT", "8791"))
TOKEN = os.environ["CUA_SHARED_SECRET"]

TEMPLATES = {
    "description": "Where is the {q} element? (Output the center coordinates of the target)",
    "intent": "I want to {q}. Please locate the target element I should interact with. "
              "(Output the center coordinates of the target)",
    "functionality": "Locate the element according to its detailed functionality description. "
                     "{q} (Output the center coordinates of the target)",
}

_lock = threading.Lock()
_state: dict = {}


def load() -> None:
    t0 = time.time()
    processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, trust_remote_code=True,
                                                 torch_dtype=torch.float32)
    model.eval().to(DEVICE)
    _state["processor"] = processor
    _state["model"] = model
    _state["load_s"] = round(time.time() - t0, 1)
    _state["device"] = DEVICE
    print(f"[i] model ready on {DEVICE} in {_state['load_s']}s", flush=True)


def ground(payload: dict) -> dict:
    processor, model = _state["processor"], _state["model"]
    img = Image.open(io.BytesIO(base64.b64decode(payload["image_b64"]))).convert("RGB")
    W, H = img.size
    mode = payload.get("mode", "description")
    prompt = TEMPLATES[mode].format(q=payload["prompt"])

    t0 = time.time()
    inputs = processor(images=img, text=prompt, return_tensors="pt").to(DEVICE, model.dtype)
    with _lock, torch.inference_mode():
        out = model.generate(**inputs, do_sample=False, max_new_tokens=32, use_cache=True)
    text = processor.tokenizer.batch_decode(out, skip_special_tokens=False)[0]
    infer_ms = round((time.time() - t0) * 1000, 1)

    m = re.search(r"<loc_(\d+)>,<loc_(\d+)>", text)
    if not m:
        return {"ok": False, "point": None, "loc": None, "image_size": [W, H],
                "prompt_used": prompt, "raw": text[-160:], "infer_ms": infer_ms}
    lx, ly = int(m.group(1)), int(m.group(2))
    return {
        "ok": True,
        "point": [round(lx / 1000 * W), round(ly / 1000 * H)],
        "loc": [lx, ly],
        "image_size": [W, H],
        "prompt_used": prompt,
        "raw": text[-160:],
        "infer_ms": infer_ms,
        "device": DEVICE,
        "load_s": _state["load_s"],
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ok": bool(_state), "model": MODEL_ID,
                                    "device": _state.get("device"),
                                    "load_s": _state.get("load_s")})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/ground":
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length))
        except Exception:
            return self._send(400, {"error": "bad json"})
        if payload.get("token") != TOKEN:
            return self._send(401, {"error": "unauthorized"})
        try:
            self._send(200, ground(payload))
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    load()
    print(f"[i] listening on 127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
