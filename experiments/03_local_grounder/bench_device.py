#!/usr/bin/env python3
"""GoClick cold vs warm latency on a chosen device (cpu | mps).

Cold = the first inference after the weights are in memory (includes any lazy
backend initialisation). Warm = median of the remaining repeats.

    DEVICE=mps python bench_device.py
"""
from __future__ import annotations

import os
import re
import statistics
import time

import torch
from PIL import Image
from transformers import AutoModelForCausalLM, AutoProcessor

DEVICE = os.environ.get("DEVICE", "cpu")
MODEL_ID = "HongxinLi/GoClick-Base"
REPEATS = int(os.environ.get("REPEATS", "5"))

TEMPLATE = "Where is the {q} element? (Output the center coordinates of the target)"

TARGETS = [
    ("search button", "the Search button", [1103, 289, 1234, 346]),
    ("to field", "the To destination input field", [257, 292, 459, 345]),
    ("one-way radio", "the One-way trip type radio button", [140, 258, 250, 282]),
    ("japan card", "the Japan destination card", [345, 469, 629, 601]),
    ("depart field", "the Depart date input field", [467, 291, 670, 344]),
    ("direct checkbox", "the Direct flights only checkbox", [232, 356, 249, 375]),
]


def main() -> None:
    if DEVICE == "mps" and not torch.backends.mps.is_available():
        raise SystemExit("MPS not available")
    if DEVICE == "mps":
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

    img = Image.open("results_frame_clean.png").convert("RGB")
    W, H = img.size

    t0 = time.time()
    processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, trust_remote_code=True,
                                                 torch_dtype=torch.float32)
    model.eval().to(DEVICE)
    load_s = time.time() - t0

    cold_sample = None
    warm_samples = []
    hits = 0
    calls = 0

    for rep in range(REPEATS):
        for name, desc, bbox in TARGETS:
            prompt = TEMPLATE.format(q=re.sub(r"^the\s+", "", desc, flags=re.I))
            inputs = processor(images=img, text=prompt, return_tensors="pt").to(DEVICE, model.dtype)
            t1 = time.time()
            with torch.inference_mode():
                out = model.generate(**inputs, do_sample=False, max_new_tokens=32, use_cache=True)
            ms = (time.time() - t1) * 1000
            text = processor.tokenizer.batch_decode(out, skip_special_tokens=False)[0]
            m = re.search(r"<loc_(\d+)>,<loc_(\d+)>", text)
            px = py = None
            if m:
                px = round(int(m.group(1)) / 1000 * W)
                py = round(int(m.group(2)) / 1000 * H)
                calls += 1
                if bbox[0] <= px <= bbox[2] and bbox[1] <= py <= bbox[3]:
                    hits += 1

            if rep == 0 and name == TARGETS[0][0]:
                cold_sample = ms
            elif rep > 0 or name != TARGETS[0][0]:
                warm_samples.append(ms)

    print(f"device={DEVICE} load_s={load_s:.1f} cold_ms={cold_sample:.0f} "
          f"warm_median_ms={statistics.median(warm_samples):.0f} "
          f"warm_min_ms={min(warm_samples):.0f} warm_max_ms={max(warm_samples):.0f} "
          f"n_warm={len(warm_samples)} hits={hits}/{calls}")


if __name__ == "__main__":
    main()
