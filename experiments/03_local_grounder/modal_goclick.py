"""GoClick-Base (0.2B) GUI grounder, served from Modal.

Stage 2 of the GoClick two-stage design: given a screenshot and a description of the
element, return the centre coordinates. The planner (Stage 1) is DeepSeek.

POST /ground  {"image_b64": str, "prompt": str, "token": str, "mode": str}
  mode: description | intent | functionality
"""
from __future__ import annotations

import base64
import io
import os
import re
import time

import modal

MODEL_ID = "HongxinLi/GoClick-Base"
MODEL_DIR = "/models/goclick-base"

base = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install("torch", "torchvision", extra_index_url="https://download.pytorch.org/whl/cpu")
    .pip_install("transformers==4.45.0", "timm", "pillow", "huggingface_hub", "sentencepiece")
    .env({"HF_HOME": "/root/.cache/huggingface", "TRANSFORMERS_OFFLINE": "0"})
)


image = base

app = modal.App("cua-goclick", image=image)
auth = modal.Secret.from_name("cua-detect-auth")

_state: dict = {}


def _load():
    if not _state:
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor
        import os as _os
        t0 = time.time()
        if not _os.path.isdir(MODEL_DIR):
            from huggingface_hub import snapshot_download
            snapshot_download(MODEL_ID, local_dir=MODEL_DIR)
        processor = AutoProcessor.from_pretrained(MODEL_DIR, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(MODEL_DIR, trust_remote_code=True,
                                                     torch_dtype=torch.float32)
        model.eval()
        _state["processor"] = processor
        _state["model"] = model
        _state["load_s"] = round(time.time() - t0, 2)
    return _state


TEMPLATES = {
    "description": "Where is the {q} element? (Output the center coordinates of the target)",
    "intent": "I want to {q}. Please locate the target element I should interact with. "
              "(Output the center coordinates of the target)",
    "functionality": "Locate the element according to its detailed functionality description. "
                     "{q} (Output the center coordinates of the target)",
}


@app.function(cpu=4, memory=8192, timeout=300, scaledown_window=600, secrets=[auth])
@modal.fastapi_endpoint(method="POST")
def ground(payload: dict):
    from fastapi import HTTPException

    if payload.get("token") != os.environ.get("CUA_SHARED_SECRET"):
        raise HTTPException(status_code=401, detail="unauthorized")

    import torch
    from PIL import Image

    t_start = time.time()
    st = _load()
    processor, model = st["processor"], st["model"]

    image_bytes = base64.b64decode(payload["image_b64"])
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    W, H = img.size

    mode = payload.get("mode", "description")
    prompt = TEMPLATES[mode].format(q=payload["prompt"])

    t0 = time.time()
    inputs = processor(images=img, text=prompt, return_tensors="pt").to(
        model.device, dtype=model.dtype)
    with torch.inference_mode():
        out = model.generate(**inputs, do_sample=False, max_new_tokens=32, use_cache=True)
    text = processor.tokenizer.batch_decode(out, skip_special_tokens=False)[0]
    infer_ms = round((time.time() - t0) * 1000, 1)

    m = re.search(r"<loc_(\d+)>,<loc_(\d+)>", text)
    if m:
        lx, ly = int(m.group(1)), int(m.group(2))
        # Florence-style locations are in a 0-999 normalised grid.
        px, py = round(lx / 1000 * W), round(ly / 1000 * H)
        ok = True
    else:
        lx = ly = px = py = None
        ok = False

    return {
        "ok": ok,
        "point": [px, py] if ok else None,
        "loc": [lx, ly] if ok else None,
        "image_size": [W, H],
        "prompt_used": prompt,
        "raw": text[-160:],
        "infer_ms": infer_ms,
        "load_s": st["load_s"],
        "total_ms": round((time.time() - t_start) * 1000, 1),
    }
