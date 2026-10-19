#!/usr/bin/env python3
"""Render the visual benchmark: ground truth, detector scoring, and VLM grounding.

Produces, in benchmark/:
    panel_ground_truth.png   every real UI element, labelled
    panel_detector.png       28 YOLO boxes coloured by outcome, misses in magenta
    panel_vlm.png            A2 vs B, each box coloured by whether the model's claim was right
    scorecard.png            the numbers behind the pictures
    metrics.json             machine-readable results
    box_table.md             per-box: truth / A2 claim / B claim
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".mpl"))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / ".cache"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from PIL import Image

from benchmark_data import GROUND_TRUTH, BOX_TRUTH

RESULTS = ROOT / "results"
OUT = ROOT / "benchmark"
OUT.mkdir(exist_ok=True)

COL = {
    "correct":   "#16a34a",
    "mislabelled": "#f59e0b",
    "duplicate": "#64748b",
    "false":     "#dc2626",
    "missed":    "#d946ef",
    "neutral":   "#94a3b8",
    "gt":        "#111827",
}

IMG = Image.open(RESULTS / "frames" / "frame_raw.png").convert("RGB")
W, H = IMG.size
REC = json.loads((RESULTS / "run_log.json").read_text())
DETS = REC["detectors"]["yolov8_ui_model"]["detections"]


def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if not inter:
        return 0.0
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua


def center_inside(box, gtbox):
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    return gtbox[0] <= cx <= gtbox[2] and gtbox[1] <= cy <= gtbox[3]


# ---- score the detector against ground truth -------------------------------
taken: dict[int, int] = {}          # gt index -> detection id
det_status: dict[int, str] = {}
det_gt: dict[int, int] = {}

for d in sorted(DETS, key=lambda x: -x["confidence"]):
    best, best_iou = None, 0.0
    for gi, (_n, gb, _e) in enumerate(GROUND_TRUTH):
        v = iou(d["bbox"], gb)
        if v > best_iou:
            best, best_iou = gi, v

    if best_iou >= 0.40 and best is not None:
        if best in taken:
            det_status[d["id"]] = "duplicate"
        else:
            taken[best] = d["id"]
            det_gt[d["id"]] = best
            det_status[d["id"]] = "correct" if d["label"] in GROUND_TRUTH[best][2] else "mislabelled"
    elif any(center_inside(d["bbox"], gb) for _n, gb, _e in GROUND_TRUTH):
        det_status[d["id"]] = "duplicate"      # nested text inside an already-found element
    else:
        det_status[d["id"]] = "false"

missed = [gi for gi in range(len(GROUND_TRUTH)) if gi not in taken]
counts = {k: sum(1 for v in det_status.values() if v == k) for k in COL if k in
          ("correct", "mislabelled", "duplicate", "false")}

detector_metrics = {
    "detections": len(DETS),
    "ground_truth_elements": len(GROUND_TRUTH),
    "correct": counts["correct"],
    "mislabelled": counts["mislabelled"],
    "duplicate": counts["duplicate"],
    "false_positive": counts["false"],
    "missed": len(missed),
    "recall": round(len(taken) / len(GROUND_TRUTH), 3),
    "precision": round((counts["correct"] + counts["mislabelled"]) / len(DETS), 3),
    "label_accuracy": round(counts["correct"] / max(1, counts["correct"] + counts["mislabelled"]), 3),
    "missed_elements": [GROUND_TRUTH[g][0] for g in missed],
}

# ---- VLM audit -------------------------------------------------------------
vlm_metrics = {}
for col, label in ((1, "A2_model_swap"), (2, "B_fixed")):
    verdicts = {bid: v[col][1] for bid, v in BOX_TRUTH.items() if v[col][0]}
    addressed = len(verdicts)
    correct = sum(1 for x in verdicts.values() if x == "correct")
    partial = sum(1 for x in verdicts.values() if x == "partial")
    vlm_metrics[label] = {
        "boxes_addressed": addressed,
        "correct": correct,
        "partial": partial,
        "wrong": sum(1 for x in verdicts.values() if x == "wrong"),
        "accuracy_exact": round(correct / max(1, addressed), 3),
        "accuracy_lenient": round((correct + partial) / max(1, addressed), 3),
    }

metrics = {"detector": detector_metrics, "vlm": vlm_metrics}
(OUT / "metrics.json").write_text(json.dumps(metrics, indent=2))

# ---- per-box table ---------------------------------------------------------
lines = ["| box | detector says | actually covers | A2 claim | B claim |",
         "|----:|---|---|---|---|"]
for d in DETS:
    bid = d["id"]
    truth = BOX_TRUTH[bid][0]
    a2 = BOX_TRUTH[bid][1][0] or "—"
    b = BOX_TRUTH[bid][2][0] or "—"
    lines.append(f"| {bid} | {d['label']} {d['confidence']:.2f} | {truth} | {a2} | {b} |")
(OUT / "box_table.md").write_text("\n".join(lines) + "\n")


# ---- drawing helpers -------------------------------------------------------
def canvas(title: str, subtitle: str = ""):
    header = 0.95                       # inches reserved above the screenshot
    fig = plt.figure(figsize=(W / 100, H / 100 + header), dpi=100)
    ax = fig.add_axes([0, 0, 1, (H / 100) / (H / 100 + header)])
    ax.imshow(IMG)
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")
    fig.text(0.008, 0.995, title, fontsize=15, fontweight="bold", va="top",
             bbox=dict(facecolor="white", edgecolor="none", pad=2))
    if subtitle:
        fig.text(0.008, 0.962, subtitle, fontsize=9.5, color="#374151", va="top",
                 bbox=dict(facecolor="white", edgecolor="none", pad=2))
    return fig, ax


def box(ax, bb, color, label, lw=2.0, ls="-", alpha=1.0, fs=7.2, dy=-3):
    x1, y1, x2, y2 = bb
    ax.add_patch(mpatches.Rectangle((x1, y1), x2 - x1, y2 - y1, fill=False,
                                    edgecolor=color, linewidth=lw,
                                    linestyle=ls, alpha=alpha, zorder=3))
    if label:
        ax.text(x1 + 1, y1 + dy, label, fontsize=fs, color="white", va="bottom",
                zorder=4, bbox=dict(facecolor=color, edgecolor="none", pad=1.2, alpha=0.95))


# ---- panel 1: ground truth -------------------------------------------------
fig, ax = canvas("Benchmark 1 — Ground truth",
                 f"{len(GROUND_TRUTH)} real UI elements of the container page (hand-labelled)")
for i, (name, bb, _e) in enumerate(GROUND_TRUTH, start=1):
    box(ax, bb, COL["gt"], f"GT{i} {name}", lw=1.4, fs=6.8)
fig.savefig(OUT / "panel_ground_truth.png", facecolor="white")
plt.close(fig)

# ---- panel 2: detector outcomes -------------------------------------------
fig, ax = canvas(
    "Benchmark 2 — YOLOv8 detections scored against ground truth",
    f"correct {counts['correct']}  ·  mislabelled {counts['mislabelled']}  ·  duplicate {counts['duplicate']}  ·  "
    f"false pos {counts['false']}  ·  missed {len(missed)}   "
    f"(recall {detector_metrics['recall']:.0%}, precision {detector_metrics['precision']:.0%}, "
    f"label acc {detector_metrics['label_accuracy']:.0%})")
for d in DETS:
    box(ax, d["bbox"], COL[det_status[d["id"]]], f"#{d['id']} {d['label']}", lw=1.8)
for gi in missed:
    name, bb, _e = GROUND_TRUTH[gi]
    box(ax, bb, COL["missed"], f"MISSED: {name}", lw=2.2, ls=(0, (4, 3)), fs=8)
handles = [mpatches.Patch(color=COL[k], label=v) for k, v in [
    ("correct", "correct box + correct label"),
    ("mislabelled", "correct box, wrong label"),
    ("duplicate", "duplicate / nested box"),
    ("false", "false positive"),
    ("missed", "ground-truth element missed")]]
ax.legend(handles=handles, loc="lower right", fontsize=7.4, framealpha=0.92)
fig.savefig(OUT / "panel_detector.png", facecolor="white")
plt.close(fig)

# ---- panel 3+4: VLM grounding ---------------------------------------------
fig = plt.figure(figsize=(W / 100, 2 * (H / 100) + 1.1), dpi=100)
for row, (col, key, title) in enumerate([
        (1, "A2_model_swap", "A2 — raw image + flat text list (as published)"),
        (2, "B_fixed", "B — annotated image + structured JSON (fixed)")]):
    m = vlm_metrics[key]
    ax = fig.add_axes([0, 0.505 - row * 0.49, 1, 0.41])
    ax.imshow(IMG)
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")
    ax.set_title(
        f"{title}   —   {m['correct']}/{m['boxes_addressed']} box claims correct "
        f"({m['accuracy_exact']:.0%} exact, {m['accuracy_lenient']:.0%} lenient), "
        f"{m['wrong']} wrong", fontsize=11.5, loc="left", pad=6)
    for d in DETS:
        claim, verdict = BOX_TRUTH[d["id"]][col]
        if not claim:
            box(ax, d["bbox"], COL["neutral"], f"#{d['id']}", lw=1.0, alpha=0.55, fs=6.2)
            continue
        c = {"correct": "correct", "partial": "mislabelled", "wrong": "false"}[verdict]
        box(ax, d["bbox"], COL[c], f"#{d['id']}", lw=2.0, fs=6.8)
handles = [mpatches.Patch(color=COL[k], label=v) for k, v in [
    ("correct", "claim correct"), ("mislabelled", "claim partly right"),
    ("false", "claim wrong"), ("neutral", "box never mentioned")]]
fig.legend(handles=handles, loc="center", bbox_to_anchor=(0.5, 0.482),
           ncol=4, fontsize=9, frameon=False)
fig.savefig(OUT / "panel_vlm.png", facecolor="white")
plt.close(fig)

# ---- scorecard -------------------------------------------------------------
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.6), dpi=110)
labels = ["A1\nas published", "A2\nmodel swap", "B\nfixed"]
vals = [0.0, vlm_metrics["A2_model_swap"]["accuracy_exact"], vlm_metrics["B_fixed"]["accuracy_exact"]]
bars = ax1.bar(labels, [v * 100 for v in vals], color=["#9ca3af", "#ef4444", "#16a34a"], width=0.55)
for b, lab, v in zip(bars, ["0 / 0\n(no boxes existed)", "1 / 13", "16 / 28"], vals):
    ax1.text(b.get_x() + b.get_width() / 2, b.get_height() + 2, f"{v*100:.0f}%\n{lab}",
             ha="center", fontsize=9.5)
ax1.set_ylim(0, 100)
ax1.set_ylabel("% of addressed boxes mapped to the correct element")
ax1.set_title("VLM box grounding: does the model name the right element?", fontsize=11)
ax1.grid(axis="y", alpha=0.25)
ax1.set_axisbelow(True)

names = ["recall\n(GT found)", "precision\n(real objects)", "label\naccuracy"]
scores = [detector_metrics["recall"], detector_metrics["precision"], detector_metrics["label_accuracy"]]
bars2 = ax2.bar(names, [s * 100 for s in scores], color=["#3b82f6", "#3b82f6", "#f59e0b"], width=0.55)
for b, s in zip(bars2, scores):
    ax2.text(b.get_x() + b.get_width() / 2, b.get_height() + 2, f"{s*100:.0f}%", ha="center", fontsize=10)
ax2.set_ylim(0, 100)
ax2.set_title(f"YOLOv8 detector (yolov8_ui_model, {len(DETS)} boxes vs {len(GROUND_TRUTH)} GT)", fontsize=11)
ax2.grid(axis="y", alpha=0.25)
ax2.set_axisbelow(True)

fig.suptitle("Visual benchmark — container UI, 1280×800, DeepSeek-V4.1-Flash-1017",
             fontsize=12.5, fontweight="bold")
fig.tight_layout(rect=[0, 0, 1, 0.94])
fig.savefig(OUT / "scorecard.png", facecolor="white")
plt.close(fig)

print(json.dumps(metrics, indent=2))
print(f"\nwritten to {OUT}")
