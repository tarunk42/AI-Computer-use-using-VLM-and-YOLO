#!/usr/bin/env python3
"""Validate GoClick grounding coordinates against known elements on the task page."""
from __future__ import annotations

import re
import sys
import time

import torch
from PIL import Image, ImageDraw
from transformers import AutoModelForCausalLM, AutoProcessor

MODEL_ID = "HongxinLi/GoClick-Base"

TEMPLATES = {
    "description": "Where is the {q} element? (Output the center coordinates of the target)",
    "intent": "I want to {q}. Please locate the target element I should interact with. "
              "(Output the center coordinates of the target)",
}

# element name -> (expected bbox, description prompt)
TARGETS = {
    "search button":      ([1103, 289, 1234, 346], "the Search button"),
    "to field":           ([257, 292, 459, 345], "the To destination input field"),
    "one-way radio":      ([140, 258, 250, 282], "the One-way trip type radio button"),
    "japan card":         ([345, 469, 629, 601], "the Japan destination card"),
    "depart field":       ([467, 291, 670, 344], "the Depart date input field"),
    "direct checkbox":    ([232, 356, 249, 375], "the Direct flights only checkbox"),
}


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "results_frame.png"
    img = Image.open(path).convert("RGB")
    W, H = img.size
    print(f"image {W}x{H}")

    t0 = time.time()
    processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, trust_remote_code=True,
                                                 torch_dtype=torch.float32)
    model.eval()
    print(f"model loaded in {time.time()-t0:.1f}s")

    draw = ImageDraw.Draw(img)
    hits = 0
    for name, (bbox, desc) in TARGETS.items():
        prompt = TEMPLATES["description"].format(q=desc)
        t1 = time.time()
        inputs = processor(images=img, text=prompt, return_tensors="pt").to(model.device, model.dtype)
        with torch.inference_mode():
            out = model.generate(**inputs, do_sample=False, max_new_tokens=32, use_cache=True)
        text = processor.tokenizer.batch_decode(out, skip_special_tokens=False)[0]
        ms = (time.time() - t1) * 1000

        m = re.search(r"<loc_(\d+)>,<loc_(\d+)>", text)
        if not m:
            print(f"  {name:16s} NO LOC  raw={text[-60:]}")
            continue
        lx, ly = int(m.group(1)), int(m.group(2))
        px, py = round(lx / 1000 * W), round(ly / 1000 * H)
        inside = bbox[0] <= px <= bbox[2] and bbox[1] <= py <= bbox[3]
        hits += inside
        print(f"  {name:16s} loc=({lx},{ly}) px=({px},{py}) expected={bbox} "
              f"{'HIT' if inside else 'miss'}  {ms:.0f}ms")

        draw.ellipse([px - 9, py - 9, px + 9, py + 9], outline=(220, 38, 38), width=3)
        draw.text((px + 12, py - 7), name, fill=(220, 38, 38))
        draw.rectangle(bbox, outline=(22, 163, 74), width=1)

    print(f"\nhits {hits}/{len(TARGETS)}")
    img.save("goclick_probe.png")
    print("saved goclick_probe.png")


if __name__ == "__main__":
    main()
