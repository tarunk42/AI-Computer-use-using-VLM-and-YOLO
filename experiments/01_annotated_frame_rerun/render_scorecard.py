#!/usr/bin/env python3
"""Scorecard for the rerun: VLM grounding per run (left) and detector recall per model (right)."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".mpl"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

audit = json.loads((ROOT / "benchmark" / "vlm_audit.json").read_text())
dets = json.loads((ROOT / "results" / "detectors.json").read_text())["models"]

SURFACE, INK, INK2, GRID = "#fcfcfb", "#1f1f1e", "#5f5e58", "#e6e5e0"
BLUE, ORANGE = "#2a78d6", "#eb6834"   # validated categorical slots 1-2 (light): VLM variants
AQUA, YELLOW = "#1baf7a", "#eda100"   # validated slots 3-4: detector thresholds (values labelled)

plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "text.color": INK})
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.8), facecolor=SURFACE,
                               gridspec_kw={"width_ratios": [1.15, 1]})
for ax in (ax1, ax2):
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_ylim(0, 100)
    ax.set_ylabel("%")

# --- left: B vs A2, one column per run -------------------------------------
runs = [("prior_run_rescored", "prior_run", "prior run\n(rescored)"),
        ("run1", "run1", "rerun 1"), ("run2", "run2", "rerun 2"), ("run3", "run3", "rerun 3")]
x = range(len(runs))
w = 0.36
for i, (bk, ak, _lbl) in enumerate(runs):
    b, a = audit["B_fixed"][bk], audit["A2_model_swap"][ak]
    bv, av = 100 * b["correct"] / b["addressed"], 100 * a["correct"] / a["addressed"]
    ax1.bar(i - w / 2 - 0.01, bv, w, color=BLUE)
    few = a["addressed"] < 10  # too few one-to-one claims to compare: hatch it
    ax1.bar(i + w / 2 + 0.01, av, w, color=SURFACE if few else ORANGE, edgecolor=ORANGE,
            hatch="///" if few else None, lw=1.2)
    if few:
        ax1.text(i + w / 2, av + 7, "only 5 boxes\nnamed", ha="center", fontsize=8, color=INK2)
    ax1.text(i - w / 2, bv + 2, f"{b['correct']}/{b['addressed']}", ha="center", fontsize=9, color=INK)
    ax1.text(i + w / 2, av + 2, f"{a['correct']}/{a['addressed']}", ha="center", fontsize=9, color=INK)
ax1.set_xticks(list(x), [r[2] for r in runs])
ax1.set_title("DeepSeek box grounding: share of box claims naming the right element", fontsize=11, loc="left")
ax1.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=BLUE), plt.Rectangle((0, 0), 1, 1, color=ORANGE)],
           labels=["B: annotated image + JSON boxes", "A2: raw image + text list"],
           frameon=False, loc="upper right", fontsize=9)

# --- right: detector recall at two thresholds, single series per panel ------
names = list(dets)
r50 = [100 * dets[n]["conf_0.5"]["recall"] for n in names]
r25 = [100 * dets[n]["conf_0.25"]["recall"] for n in names]
for i, n in enumerate(names):
    ax2.bar(i - w / 2 - 0.01, r50[i], w, color=AQUA)
    ax2.bar(i + w / 2 + 0.01, r25[i], w, color=YELLOW)
    ax2.text(i - w / 2, r50[i] + 2, f"{r50[i]:.0f}", ha="center", fontsize=9)
    ax2.text(i + w / 2, r25[i] + 2, f"{r25[i]:.0f}", ha="center", fontsize=9)
ax2.set_xticks(range(len(names)),
               [f"{n}\n({dets[n]['family']}, {dets[n]['median_ms']:.0f} ms)" for n in names], fontsize=9)
ax2.set_title("Detector recall vs 31 hand-labelled elements", fontsize=11, loc="left")
ax2.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=AQUA), plt.Rectangle((0, 0), 1, 1, color=YELLOW)],
           labels=["confidence ≥ 0.5", "confidence ≥ 0.25"], frameon=False, loc="upper right", fontsize=9)

fig.suptitle("Rerun benchmark — SkyHook container page, 1280×800, DeepSeek V4.1 Flash 1017 (thinking off)",
             fontsize=12, fontweight="bold", x=0.01, ha="left")
fig.tight_layout()
out = ROOT / "benchmark" / "scorecard.png"
fig.savefig(out, dpi=130, facecolor=SURFACE)
print(out)
