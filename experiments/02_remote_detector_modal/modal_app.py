"""Modal deployment of the repo's YOLOv8 UI detector.

Two endpoints over the same weights:
    detect_cpu  - 2 cores, CPU-only torch wheels (the cheap path)
    detect_gpu  - T4, default CUDA torch wheels

The CPU image is deliberately the light one: CPU wheels keep the image small and the
cold start short, which is the whole point of measuring it.

Deploy:  ./ .venv/bin/modal deploy modal_app.py
Set MODAL_INCLUDE_GPU=1 to also register/build the GPU endpoint.
"""
from __future__ import annotations

import base64
import io
import os
import time

import modal

from pathlib import Path
REPO = str(Path(__file__).resolve().parents[2])
WEIGHTS_LOCAL = f"{REPO}/models/yolov8_ui_model.pt"
WEIGHTS_REMOTE = "/models/yolov8_ui_model.pt"

_pip = ["fastapi[standard]", "ultralytics==8.4.193", "pillow", "numpy"]

# CPU-only torch: no CUDA payload, so the image stays small.
image_cpu = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install("torch", "torchvision", extra_index_url="https://download.pytorch.org/whl/cpu")
    .pip_install(*_pip)
    .run_commands("python -m pip uninstall -y opencv-python && python -m pip install opencv-python-headless")
    .add_local_file(WEIGHTS_LOCAL, remote_path=WEIGHTS_REMOTE)
)

image_gpu = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install(*_pip)
    .run_commands("python -m pip uninstall -y opencv-python && python -m pip install opencv-python-headless")
    .add_local_file(WEIGHTS_LOCAL, remote_path=WEIGHTS_REMOTE)
)

app = modal.App("cua-ui-detect")
auth = modal.Secret.from_name("cua-detect-auth")

_model = None


def _get_model():
    global _model
    if _model is None:
        from ultralytics import YOLO
        _model = YOLO(WEIGHTS_REMOTE)
    return _model


def _detect(payload: dict) -> dict:
    """payload: {"image_b64": str, "conf": float, "token": str}"""
    from fastapi import HTTPException
    if payload.get("token") != os.environ.get("CUA_SHARED_SECRET"):
        raise HTTPException(status_code=401, detail="unauthorized")

    import numpy as np
    from PIL import Image

    t0 = time.time()
    img_bytes = base64.b64decode(payload["image_b64"])
    image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    device = "cpu"
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        pass
    model = _get_model()

    t1 = time.time()
    res = model.predict(np.array(image), verbose=False, device=device)[0]
    t2 = time.time()

    conf_threshold = float(payload.get("conf", 0.5))
    dets = []
    for box in res.boxes:
        conf = float(box.conf[0])
        if conf < conf_threshold:
            continue
        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int).tolist()
        dets.append({
            "label": res.names[int(box.cls[0])],
            "confidence": round(conf, 4),
            "bbox": [x1, y1, x2, y2],
        })
    dets.sort(key=lambda d: -d["confidence"])
    for i, d in enumerate(dets, start=1):
        d["id"] = i

    return {
        "ok": True,
        "device": device,
        "task_id": os.environ.get("MODAL_TASK_ID", ""),
        "image_size": list(image.size),
        "decode_ms": round((t1 - t0) * 1000, 1),
        "inference_ms": round((t2 - t1) * 1000, 1),
        "total_ms": round((t2 - t0) * 1000, 1),
        "count": len(dets),
        "detections": dets,
    }


@app.function(image=image_cpu, cpu=2, memory=2048, timeout=120, scaledown_window=300, secrets=[auth])
@modal.fastapi_endpoint(method="POST")
def detect_cpu(payload: dict):
    return _detect(payload)


if os.environ.get("MODAL_INCLUDE_GPU") == "1":
    @app.function(image=image_gpu, gpu="T4", cpu=2, memory=4096, timeout=120, scaledown_window=300, secrets=[auth])
    @modal.fastapi_endpoint(method="POST")
    def detect_gpu(payload: dict):
        return _detect(payload)
