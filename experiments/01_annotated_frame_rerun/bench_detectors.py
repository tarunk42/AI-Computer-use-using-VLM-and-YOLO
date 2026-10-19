#!/usr/bin/env python3
"""Score every fine-tuned YOLO model in the repo against the hand-labelled ground truth.

Same matching rules as the original render_benchmark.py:
  - a detection matches the unclaimed ground-truth element with the highest IoU, if IoU >= 0.40
  - otherwise, if its centre sits inside some element, it is a duplicate / nested box
  - otherwise it is a false positive
Label accuracy only applies to the web models; the RICO models use a different class set,
so they are scored on boxes alone.

Usage: bench_detectors.py <frame.png> <out.json>
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("YOLO_CONFIG_DIR", str(ROOT / ".ultralytics"))

import numpy as np
from PIL import Image
from ultralytics import YOLO

sys.path.insert(0, str(ROOT))
from benchmark_data import GROUND_TRUTH

MODELS_DIR = ROOT.parents[1] / "models"
MODELS = {
    "yolov8_ui_model": ("web", MODELS_DIR / "yolov8_ui_model.pt"),
    "yolov8_ui_100":   ("web", MODELS_DIR / "yolov8_ui_100.pt"),
    "chunk01_best":    ("rico", MODELS_DIR / "chunk01_best.pt"),
    "chunk02_best":    ("rico", MODELS_DIR / "chunk02_best.pt"),
}
THRESHOLDS = [0.5, 0.25]
IOU_MIN = 0.40


def iou(a, b):
    ix1, iy1, ix2, iy2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    area = lambda r: (r[2] - r[0]) * (r[3] - r[1])
    return inter / (area(a) + area(b) - inter) if inter else 0.0


def centre_inside(box, gt):
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return gt[0] <= cx <= gt[2] and gt[1] <= cy <= gt[3]


def score(dets, family):
    taken, status = {}, []
    for d in sorted(dets, key=lambda d: -d["conf"]):
        best, best_iou = None, IOU_MIN
        for gi, (_n, gb, _e) in enumerate(GROUND_TRUTH):
            if gi in taken:
                continue
            v = iou(d["bbox"], gb)
            if v >= best_iou:
                best, best_iou = gi, v
        if best is not None:
            taken[best] = d
            ok = family == "web" and d["label"] in GROUND_TRUTH[best][2]
            status.append("correct" if ok or family == "rico" else "mislabelled")
        elif any(centre_inside(d["bbox"], gb) for _n, gb, _e in GROUND_TRUTH):
            status.append("duplicate")
        else:
            status.append("false_positive")
    n = len(dets)
    matched = len(taken)
    out = {
        "detections": n,
        "matched": matched,
        "duplicate": status.count("duplicate"),
        "false_positive": status.count("false_positive"),
        "missed": [GROUND_TRUTH[g][0] for g in range(len(GROUND_TRUTH)) if g not in taken],
        "recall": round(matched / len(GROUND_TRUTH), 3),
        # precision = boxes on a real element (matched or nested) / all boxes
        "precision": round((matched + status.count("duplicate")) / n, 3) if n else None,
    }
    if family == "web":
        out["mislabelled"] = status.count("mislabelled")
        out["label_accuracy"] = round(status.count("correct") / matched, 3) if matched else None
    return out


def main():
    frame = np.array(Image.open(sys.argv[1]).convert("RGB"))
    report = {"frame": sys.argv[1], "ground_truth_elements": len(GROUND_TRUTH), "models": {}}
    for name, (family, path) in MODELS.items():
        model = YOLO(str(path))
        t0 = time.time(); model.predict(frame, verbose=False); cold = time.time() - t0
        times = []
        for _ in range(10):
            t0 = time.time(); res = model.predict(frame, verbose=False)[0]; times.append(time.time() - t0)
        times.sort()
        raw = [{"label": res.names[int(b.cls[0])], "conf": float(b.conf[0]),
                "bbox": b.xyxy[0].cpu().numpy().astype(int).tolist()} for b in res.boxes]
        entry = {"family": family, "classes": list(res.names.values()),
                 "first_call_ms": round(cold * 1000, 1),
                 "median_ms": round(times[5] * 1000, 1), "p90_ms": round(times[8] * 1000, 1),
                 "max_conf": round(max((d["conf"] for d in raw), default=0), 3)}
        for t in THRESHOLDS:
            entry[f"conf_{t}"] = score([d for d in raw if d["conf"] >= t], family)
        report["models"][name] = entry
        c = entry["conf_0.5"]
        prec = "n/a" if c["precision"] is None else f"{c['precision']:.0%}"
        print(f"{name:16s} {family:4s} median {entry['median_ms']:6.1f} ms | @0.5: {c['detections']:2d} boxes, "
              f"recall {c['recall']:.0%}, precision {prec} | @0.25 recall {entry['conf_0.25']['recall']:.0%}")
    Path(sys.argv[2]).write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
