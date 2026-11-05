"""GoClick-Base grounder on a Modal GPU.

POST /  {"token", "image_b64", "targets": ["the Search button", ...], "mode": "description"}
     -> {"results": [{"target", "point": [x, y] | null, "loc", "raw", "ms"}], "gpu_ms", "decode_ms", "cold"}

Several targets can share one upload; the image is decoded and encoded once.
Weights are baked into the image at build time, so a cold start loads from local disk.
"""
from __future__ import annotations

import modal

MODEL_ID = "HongxinLi/GoClick-Base"
MODEL_DIR = "/model"
GPU = ["T4", "L4"]  # cheapest first; fallbacks avoid capacity waits

TEMPLATES = {
    "description": "Where is the {q} element? (Output the center coordinates of the target)",
    "intent": "I want to {q}. Please locate the target element I should interact with. "
              "(Output the center coordinates of the target)",
}


def _download():
    from huggingface_hub import snapshot_download
    snapshot_download(MODEL_ID, local_dir=MODEL_DIR)


image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch==2.5.1", "torchvision==0.20.1", "transformers==4.45.0", "timm==1.0.15",
                 "einops", "pillow", "huggingface_hub", "fastapi[standard]")
    .run_function(_download)
)

app = modal.App("guided-cua-goclick", image=image)


@app.cls(gpu=GPU, scaledown_window=120, secrets=[modal.Secret.from_name("guided-cua-auth")],
         max_containers=1)
class Grounder:
    @modal.enter()
    def load(self):
        import time
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor
        t0 = time.time()
        self.torch = torch
        self.processor = AutoProcessor.from_pretrained(MODEL_DIR, trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            MODEL_DIR, trust_remote_code=True, torch_dtype=torch.float16).to("cuda").eval()
        self.load_s = round(time.time() - t0, 2)
        self.calls = 0
        self.gpu = torch.cuda.get_device_name(0)

    @modal.fastapi_endpoint(method="POST")
    def ground(self, body: dict):
        import base64
        import io
        import os
        import re
        import time
        from fastapi import HTTPException
        from PIL import Image

        if body.get("token") != os.environ["GROUNDER_TOKEN"]:
            raise HTTPException(status_code=401, detail="unauthorized")
        t0 = time.time()
        img = Image.open(io.BytesIO(base64.b64decode(body["image_b64"]))).convert("RGB")
        W, H = img.size
        decode_ms = (time.time() - t0) * 1000
        tmpl = TEMPLATES[body.get("mode", "description")]

        cold = self.calls == 0
        self.calls += 1
        out, g0 = [], time.time()
        for q in body["targets"]:
            q = re.sub(r"^the\s+", "", q.strip(), flags=re.I)
            t1 = time.time()
            inputs = self.processor(images=img, text=tmpl.format(q=q), return_tensors="pt")
            inputs = {k: (v.to("cuda", self.torch.float16) if v.dtype.is_floating_point else v.to("cuda"))
                      for k, v in inputs.items()}
            with self.torch.inference_mode():
                ids = self.model.generate(**inputs, do_sample=False, max_new_tokens=16, num_beams=1)
            text = self.processor.tokenizer.batch_decode(ids, skip_special_tokens=False)[0]
            m = re.search(r"<loc_(\d+)>,<loc_(\d+)>", text)
            loc = [int(m.group(1)), int(m.group(2))] if m else None
            out.append({"target": q, "loc": loc, "raw": text[-80:],
                        "point": [round(loc[0] / 1000 * W), round(loc[1] / 1000 * H)] if loc else None,
                        "ms": round((time.time() - t1) * 1000, 1)})
        return {"results": out, "gpu_ms": round((time.time() - g0) * 1000, 1),
                "decode_ms": round(decode_ms, 1), "cold": cold, "load_s": self.load_s,
                "image_size": [W, H], "gpu": self.gpu}
