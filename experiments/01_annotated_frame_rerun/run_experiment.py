#!/usr/bin/env python3
"""
Recreation of the AI-Computer-use experiment inside a local Linux container.

Pipeline (matching the original repo's architecture):
    VNC capture  ->  YOLOv8 UI detection  ->  annotate  ->  VLM analysis

Three VLM configurations are compared on the SAME frame:
    A1  as-published : raw image + flat text detection list  (repo's vnc_vlm_loop.py behaviour)
    A2  model-swap   : same as A1, but the web-UI YOLO model
    B   fixed        : annotated image + structured JSON boxes

Everything is written to results/: frames, annotated images, JSON, markdown log.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ultralytics writes settings to ~/Library/Application Support by default; keep it local.
ROOT = Path(__file__).resolve().parent
os.environ.setdefault("YOLO_CONFIG_DIR", str(ROOT / ".ultralytics"))

import cv2
import numpy as np
from openai import OpenAI
from PIL import Image

RESULTS = Path(os.environ.get("RESULTS_DIR", ROOT / "results"))
MODELS_DIR = ROOT.parent / "AI-Computer-use-using-VLM-and-YOLO" / "models"

VNC_TARGET = os.environ.get("VNC_TARGET", "192.168.64.11::5900")
VNC_PASSWORD = os.environ.get("VNC_PASSWORD", "1234")
CONF_THRESHOLD = 0.5          # same as the repo's CONF_THRESHOLD
API_MODEL = "deepseek-flash"  # served by DeepSeek-V4.1-Flash-1017

WEB_MODEL = MODELS_DIR / "yolov8_ui_model.pt"   # web UI (button/field/link/...)
MOBILE_MODEL = MODELS_DIR / "chunk02_best.pt"   # RICO mobile UI (the repo's default)

PALETTE = [
    (56, 56, 255), (49, 160, 255), (0, 176, 80), (255, 105, 180),
    (0, 215, 255), (180, 105, 255), (60, 200, 220), (0, 128, 255),
    (128, 128, 0), (203, 192, 255),
]


def load_api_key() -> str:
    # Rerun: key comes from the environment, not a .env file
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        sys.exit("DEEPSEEK_API_KEY is not set")
    return key


def vnc_capture(dest: Path) -> float:
    """Grab one frame from the container's X11 display over VNC. Returns seconds."""
    t0 = time.time()
    subprocess.run(
        [str(ROOT / ".venv" / "bin" / "vncdotool"),
         "-s", VNC_TARGET, "--password", VNC_PASSWORD,
         "capture", str(dest)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return time.time() - t0


def timing_runs(model, frame, runs: int = 5) -> float:
    """Median inference time in seconds, after a warm-up pass."""
    model.predict(frame, verbose=False)  # warm-up (JIT / allocations)
    times = []
    for _ in range(runs):
        t0 = time.time()
        model.predict(frame, verbose=False)
        times.append(time.time() - t0)
    times.sort()
    return times[len(times) // 2]


def detect(model, frame, class_colors, conf_threshold: float = CONF_THRESHOLD) -> tuple[list[dict], float]:
    """Run YOLO and return (detections, median inference seconds)."""
    elapsed = timing_runs(model, frame)

    res = model.predict(frame, verbose=False)[0]
    dets = []
    for box in res.boxes:
        conf = float(box.conf[0])
        if conf < conf_threshold:
            continue
        cls_id = int(box.cls[0])
        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int).tolist()
        label = res.names[cls_id]
        dets.append({
            "label": label,
            "class_id": cls_id,
            "confidence": round(conf, 4),
            "bbox": [x1, y1, x2, y2],
            "center": [(x1 + x2) // 2, (y1 + y2) // 2],
        })

    dets.sort(key=lambda d: d["confidence"], reverse=True)
    for i, d in enumerate(dets, start=1):
        d["id"] = i
        d["color"] = class_colors.setdefault(d["label"], PALETTE[len(class_colors) % len(PALETTE)])
    return dets, elapsed


def annotate(frame: np.ndarray, dets: list[dict], title: str) -> np.ndarray:
    out = frame.copy()
    for d in dets:
        x1, y1, x2, y2 = d["bbox"]
        color = d["color"]
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        text = f"#{d['id']} {d['label']} {d['confidence']:.2f}"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(out, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, y1), color, -1)
        cv2.putText(out, text, (x1 + 3, max(12, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(out, title, (12, out.shape[0] - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(out, title, (12, out.shape[0] - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    return out


def b64_of(path: Path) -> str:
    import base64
    return base64.b64encode(path.read_bytes()).decode()


# --- the repo's original prompt, verbatim ----------------------------------
REPO_PROMPT = """This image has colored bounding boxes around UI elements. The detected objects are:
{detection_info}

Please analyze the UI and provide:
1. For each colored bounding box, identify the UI element type and its specific function
2. Match each detection box with its likely corresponding element in the UI (e.g., "The blue bounding box (#3) is a Search button")
3. Explain what actions a user could take with each identified element
4. Suggest a logical sequence of actions a user might perform on this screen

Focus on correlating the visible bounding boxes with their actual UI functions."""


def fixed_prompt(dets: list[dict]) -> str:
    payload = [
        {"id": d["id"], "label": d["label"], "confidence": d["confidence"],
         "bbox_xyxy": d["bbox"], "center": d["center"]}
        for d in dets
    ]
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


def call_vlm(client, image_path: Path, prompt: str, max_tokens: int, thinking: bool) -> dict:
    t0 = time.time()
    kwargs = dict(
        model=API_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64_of(image_path)}",
                               "detail": "original"}},
            ],
        }],
        max_tokens=max_tokens,
        extra_body={"thinking": {"type": "enabled" if thinking else "disabled"}},
    )
    resp = client.chat.completions.create(**kwargs)
    elapsed = time.time() - t0
    details = resp.usage.completion_tokens_details
    return {
        "text": (resp.choices[0].message.content or "").strip(),
        "model": resp.model,
        "thinking": thinking,
        "seconds": round(elapsed, 2),
        "finish_reason": resp.choices[0].finish_reason,
        "prompt_tokens": resp.usage.prompt_tokens,
        "completion_tokens": resp.usage.completion_tokens,
        "reasoning_tokens": getattr(details, "reasoning_tokens", None),
    }


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "frames").mkdir(exist_ok=True)

    client = OpenAI(api_key=load_api_key(), base_url="https://api.deepseek.com")

    from ultralytics import YOLO
    t_load = time.time()
    web_model = YOLO(str(WEB_MODEL))
    mobile_model = YOLO(str(MOBILE_MODEL))
    load_seconds = round(time.time() - t_load, 2)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[*] {stamp}  capturing {VNC_TARGET}")
    raw_path = RESULTS / "frames" / "frame_raw.png"
    cap_seconds = vnc_capture(raw_path)

    frame = np.array(Image.open(raw_path).convert("RGB"))
    print(f"[*] frame {frame.shape[1]}x{frame.shape[0]} captured in {cap_seconds:.2f}s")

    web_colors: dict[str, tuple] = {}
    mob_colors: dict[str, tuple] = {}
    web_dets, web_ms = detect(web_model, frame, web_colors)
    mob_dets, mob_ms = detect(mobile_model, frame, mob_colors)
    # the mobile model finds nothing at 0.5 on a desktop page - check how far off it is
    mob_low, _ = detect(mobile_model, frame, dict(mob_colors), conf_threshold=0.15)
    print(f"[*] yolov8_ui_model: {len(web_dets)} detections, median {web_ms*1000:.0f}ms")
    print(f"[*] chunk02_best  : {len(mob_dets)} dets @0.5, {len(mob_low)} @0.15, median {mob_ms*1000:.0f}ms")

    web_annot = annotate(frame, web_dets, "yolov8_ui_model.pt (web UI)")
    mob_annot = annotate(frame, mob_dets, "chunk02_best.pt (RICO mobile)")
    web_annot_path = RESULTS / "frame_web_annotated.png"
    mob_annot_path = RESULTS / "frame_mobile_annotated.png"
    cv2.imwrite(str(web_annot_path), cv2.cvtColor(web_annot, cv2.COLOR_RGB2BGR))
    cv2.imwrite(str(mob_annot_path), cv2.cvtColor(mob_annot, cv2.COLOR_RGB2BGR))

    # ---- VLM stage -------------------------------------------------------
    runs: list[tuple[str, Path, str, int, bool]] = []

    repo_list = "\n".join(f"- {i+1}. {d['label']} (conf: {d['confidence']:.2f})"
                          for i, d in enumerate(mob_dets))
    runs.append((
        "A1_as_published",
        raw_path,
        REPO_PROMPT.format(detection_info=repo_list or "- none"),
        900, False,
    ))

    web_list = "\n".join(f"- {i+1}. {d['label']} (conf: {d['confidence']:.2f})"
                         for i, d in enumerate(web_dets))
    runs.append((
        "A2_model_swap",
        raw_path,
        REPO_PROMPT.format(detection_info=web_list or "- none"),
        900, False,
    ))

    runs.append((
        "B_fixed",
        web_annot_path,
        fixed_prompt(web_dets),
        2000, False,
    ))

    outputs: dict[str, dict] = {}
    for name, img, prompt, max_tokens, thinking in runs:
        print(f"[*] VLM {name} (image={img.name}, thinking={thinking})")

        def brief(o: dict) -> dict:
            return {"thinking": o.get("thinking"), "max_tokens": o.get("max_tokens"),
                    "seconds": o.get("seconds"), "finish_reason": o.get("finish_reason"),
                    "completion_tokens": o.get("completion_tokens"),
                    "reasoning_tokens": o.get("reasoning_tokens"),
                    "reply_chars": len(o.get("text") or "")}

        attempts = []
        try:
            out = call_vlm(client, img, prompt, max_tokens, thinking)
        except Exception as e:  # noqa: BLE001 - keep the experiment going
            out = {"text": "", "error": f"{type(e).__name__}: {e}", "seconds": None,
                   "prompt_tokens": None, "completion_tokens": None,
                   "reasoning_tokens": None, "finish_reason": None}
        attempts.append(brief(out))

        # Thinking mode can consume the entire budget on reasoning and emit no answer.
        if thinking and not out["text"]:
            print("    -> empty reply (reasoning-only); retrying with thinking disabled")
            try:
                first = out
                out = call_vlm(client, img, prompt, 2000, False)
                out["fallback_from_thinking"] = brief(first)
            except Exception as e:  # noqa: BLE001
                out = {"text": "", "error": f"{type(e).__name__}: {e}", "seconds": None,
                       "prompt_tokens": None, "completion_tokens": None,
                       "reasoning_tokens": None, "finish_reason": None}
            attempts.append(brief(out))

        out["prompt"] = prompt
        out["image"] = img.name
        out.setdefault("thinking", thinking)  # flag actually used for the final attempt
        out["requested_thinking"] = thinking  # what was asked for before any fallback
        out["max_tokens"] = max_tokens
        out["attempts"] = attempts
        outputs[name] = out
        print(f"    -> {out.get('seconds')}s, {out.get('completion_tokens')} completion tokens, "
              f"thinking={out.get('thinking')}, reasoning={out.get('reasoning_tokens')}")
        (RESULTS / f"vlm_{name}.md").write_text(
            f"# {name}\n\nimage: `{img.name}`\n\n```\n{prompt}\n```\n\n"
            f"## response\n\n{out.get('text') or out.get('error','')}\n"
        )
        time.sleep(1.5)

    record = {
        "timestamp_utc": stamp,
        "vnc_target": VNC_TARGET,
        "frame": {"width": int(frame.shape[1]), "height": int(frame.shape[0]),
                  "capture_seconds": round(cap_seconds, 3)},
        "model_load_seconds": load_seconds,
        "api_model": API_MODEL,
        "confidence_threshold": CONF_THRESHOLD,
        "detectors": {
            "yolov8_ui_model": {"path": str(WEB_MODEL), "inference_ms": round(web_ms * 1000, 1),
                                "count": len(web_dets), "detections": web_dets},
            "chunk02_best": {"path": str(MOBILE_MODEL), "inference_ms": round(mob_ms * 1000, 1),
                             "count": len(mob_dets), "detections": mob_dets,
                             "count_at_015": len(mob_low), "detections_at_015": mob_low},
        },
        "vlm_runs": outputs,
    }
    (RESULTS / "run_log.json").write_text(json.dumps(record, indent=2))

    # ---- console summary -------------------------------------------------
    def summarise(dets):
        by = {}
        for d in dets:
            by.setdefault(d["label"], []).append(d["confidence"])
        return ", ".join(f"{k}×{len(v)} (avg {sum(v)/len(v):.2f})"
                         for k, v in sorted(by.items(), key=lambda kv: -len(kv[1])))

    print("\n================ SUMMARY ================")
    print(f"frame            : {frame.shape[1]}x{frame.shape[0]} @ {cap_seconds:.2f}s VNC capture")
    print(f"yolov8_ui_model  : {len(web_dets):2d} dets, {web_ms*1000:.0f}ms -> {summarise(web_dets)}")
    print(f"chunk02_best     : {len(mob_dets):2d} dets @0.5 ({len(mob_low)} @0.15), {mob_ms*1000:.0f}ms -> {summarise(mob_dets) or 'none'}")
    for name, out in outputs.items():
        print(f"{name:16s}: {out.get('seconds')}s, "
              f"reasoning={out.get('reasoning_tokens')}, "
              f"reply={len(out.get('text') or '')} chars")
    print(f"results          : {RESULTS}")


if __name__ == "__main__":
    main()
