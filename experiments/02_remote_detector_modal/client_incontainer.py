#!/usr/bin/env python3
"""Runs INSIDE the Linux container.

Full loop, nothing local on the host:
    scrot -> POST to Modal (YOLO on Modal's cheapest CPU) -> annotate with Pillow
          -> DeepSeek V4.1 Flash (thinking disabled) -> write results

Secrets arrive as environment variables via `container exec --env-file`; they are never
written to disk inside the container.
"""
from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path("/tmp/out")
OUT.mkdir(exist_ok=True)

MODAL_URL = os.environ["MODAL_URL"]
CUA_SHARED_SECRET = os.environ["CUA_SHARED_SECRET"]
DEEPSEEK_KEY = os.environ["DEEPSEEK_API_KEY"]
N_CALLS = int(os.environ.get("N_CALLS", "8"))

FONT_PATH = "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"
PALETTE = [(220, 38, 38), (22, 163, 74), (37, 99, 235), (217, 70, 239),
           (245, 158, 11), (13, 148, 136), (124, 58, 237), (82, 82, 91)]


def log(msg: str) -> None:
    print(msg, flush=True)


def capture() -> tuple[Path, float]:
    path = OUT / "frame.png"
    t0 = time.time()
    subprocess.run(["scrot", "-o", "-z", str(path)], check=True,
                   env={**os.environ, "DISPLAY": ":0"})
    return path, (time.time() - t0) * 1000


def post_json(url: str, payload: dict, headers: dict, timeout: int = 180) -> tuple[dict, dict, float]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        status = dict(resp.headers)
    return json.loads(raw), status, (time.time() - t0) * 1000


def detect(image_b64: str) -> tuple[dict, float]:
    data, _h, wall = post_json(MODAL_URL, {"image_b64": image_b64, "conf": 0.5,
                                           "token": CUA_SHARED_SECRET}, {})
    return data, wall


def annotate(image: Image.Image, dets: list[dict]) -> Image.Image:
    out = image.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype(FONT_PATH, 15)
    except Exception:
        font = ImageFont.load_default()
    for d in dets:
        color = PALETTE[(d["id"] - 1) % len(PALETTE)]
        x1, y1, x2, y2 = d["bbox"]
        draw.rectangle([x1, y1, x2, y2], outline=color, width=2)
        text = f"#{d['id']} {d['label']} {d['confidence']:.2f}"
        tb = draw.textbbox((0, 0), text, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        ty = max(0, y1 - th - 6)
        draw.rectangle([x1, ty, x1 + tw + 6, ty + th + 6], fill=color)
        draw.text((x1 + 3, ty + 2), text, fill=(255, 255, 255), font=font)
    return out


def fixed_prompt(dets: list[dict]) -> str:
    payload = [{"id": d["id"], "label": d["label"], "confidence": d["confidence"],
                "bbox_xyxy": d["bbox"]} for d in dets]
    return f"""You are analysing a screenshot of a Linux desktop application.
Numbered, coloured bounding boxes are drawn on the image; each box is labelled "#<id> <label> <confidence>".

The detector reported these elements (JSON):
{json.dumps(payload, indent=2)}

Answer with these sections:
1. BOX MAPPING - one line per box id: what the element actually is, in the page.
2. DETECTOR ERRORS - boxes that are mislabelled, misplaced or duplicates.
3. MISSING ELEMENTS - important interactive elements that have no box.
4. ACTION SEQUENCE - to perform a flight search, list the elements to interact with, in order, using box ids where available.

Be concrete and reference box ids. Do not invent box ids that are not in the JSON."""


def ask_vlm(image_path: Path, dets: list[dict]) -> dict:
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    payload = {
        "model": "deepseek-flash",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": fixed_prompt(dets)},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "original"}},
        ]}],
        "max_tokens": 2000,
        "thinking": {"type": "disabled"},
    }
    data, _h, wall = post_json(
        "https://api.deepseek.com/chat/completions", payload,
        {"Authorization": f"Bearer {DEEPSEEK_KEY}"}, timeout=300)
    msg = data["choices"][0]["message"]["content"] or ""
    usage = data.get("usage", {}) or {}
    details = usage.get("completion_tokens_details") or {}
    return {"text": msg.strip(), "seconds": round(wall / 1000, 2),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "reasoning_tokens": details.get("reasoning_tokens"),
            "finish_reason": data["choices"][0].get("finish_reason")}


def main() -> None:
    log(f"[i] client running inside container: {os.uname().sysname} {os.uname().release}")
    runs = []
    frame_path = None

    for i in range(N_CALLS):
        cap_ms = None
        if frame_path is None or i % 3 == 0:
            frame_path, cap_ms = capture()
        img_bytes = frame_path.read_bytes()

        try:
            det, wall_ms = detect(base64.b64encode(img_bytes).decode())
        except urllib.error.HTTPError as e:
            log(f"[!] modal HTTP {e.code}: {e.read()[:400]!r}")
            sys.exit(1)

        run = {
            "call": i + 1,
            "capture_ms": round(cap_ms, 1) if cap_ms is not None else None,
            "upload_bytes": len(img_bytes),
            "modal_wall_ms": round(wall_ms, 1),
            "modal_total_ms": det.get("total_ms"),
            "modal_inference_ms": det.get("inference_ms"),
            "modal_decode_ms": det.get("decode_ms"),
            "net_ms": round(wall_ms - (det.get("total_ms") or 0), 1),
            "device": det.get("device"),
            "task_id": det.get("task_id", ""),
            "count": det.get("count"),
        }
        runs.append(run)
        log(f"[{i+1}/{N_CALLS}] wall={run['modal_wall_ms']:.0f}ms "
            f"(net {run['net_ms']:.0f} + infer {run['modal_inference_ms']}) "
            f"dets={run['count']} device={run['device']} task={run['task_id'][:8]}")

        if i == 0:
            image = Image.open(frame_path)
            annotated = annotate(image, det["detections"])
            annotated.save(OUT / "annotated.png")
            log("[i] calling DeepSeek (thinking disabled)")
            vlm = ask_vlm(OUT / "annotated.png", det["detections"])
            log(f"    reply {len(vlm['text'])} chars in {vlm['seconds']}s "
                f"({vlm['completion_tokens']} tokens, finish={vlm['finish_reason']})")
            (OUT / "vlm.md").write_text(f"## response\n\n{vlm['text']}\n")

    (OUT / "detections_first.json").write_text(json.dumps(runs[0], indent=2))
    summary = {
        "runs": runs,
        "vlm": vlm,
        "container": {"system": os.uname().sysname, "release": os.uname().release},
    }
    (OUT / "run_modal.json").write_text(json.dumps(summary, indent=2))
    log(f"[i] wrote {OUT}")


if __name__ == "__main__":
    main()
