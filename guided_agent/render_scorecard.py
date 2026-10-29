#!/usr/bin/env python3
"""Scorecard: GoClick hit rate per real website (left) and where a guided step's time goes (right)."""
import glob
import json
import os
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".mpl"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SURFACE, INK, INK2, GRID = "#fcfcfb", "#1f1f1e", "#5f5e58", "#e6e5e0"
BLUE = "#2a78d6"                               # single series: hit rate
STAGES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#8b5cf6"]  # validated categorical order

g = json.loads((ROOT / "benchmark" / "grounding.json").read_text())["summary"]
pages = {k: v for k, v in g["pages"].items() if v.get("sampled")}
order = sorted(pages, key=lambda k: pages[k]["hits"] / pages[k]["sampled"])

task_file = sorted(glob.glob(str(ROOT / "results" / "tasks_*.json")))[-1]
tasks = json.loads(Path(task_file).read_text())
steps = [s for t in tasks for s in t["trace"]]
plan = st.median(s["plan_ms"] for s in steps if s["plan_ms"])
gr = [s["ground"] for s in steps if s.get("ground") and not s["ground"].get("cold")]
net = st.median(x["network_ms"] for x in gr)
gpu = st.median(x["gpu_ms"] for x in gr)
act = st.median(s["exec_ms"] for s in steps if s.get("exec_ms"))
cap = 30  # screenshot via the control server (measured separately)

plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "text.color": INK})
fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5), facecolor=SURFACE, gridspec_kw={"width_ratios": [1.1, 1]})
for ax in (a1, a2):
    ax.set_facecolor(SURFACE)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)

vals = [100 * pages[k]["hits"] / pages[k]["sampled"] for k in order]
a1.barh(range(len(order)), vals, color=BLUE, height=0.62)
for i, k in enumerate(order):
    a1.text(vals[i] + 1, i, f"{pages[k]['hits']}/{pages[k]['sampled']}", va="center", fontsize=9)
a1.set_yticks(range(len(order)), [k.replace("_", " ") for k in order])
a1.set_xlim(0, 110)
a1.set_xlabel("% of elements hit")
o = g["overall"]
a1.set_title(f"GoClick on live websites: {o['hit']:.1%} of {o['n']} elements", fontsize=11, loc="left")

labels = ["screenshot", "plan (DeepSeek)", "network to Modal", "GoClick GPU", "act + settle start"]
ms = [cap, plan, net, gpu, act]
left = 0
for lab, v, c in zip(labels, ms, STAGES):
    a2.barh([0], [v], left=left, color=c, height=0.5, edgecolor=SURFACE, lw=2)
    left += v
a2.set_yticks([])
a2.set_xlabel("milliseconds per step (median, warm)")
a2.set_title(f"One guided step ≈ {left/1000:.1f} s before your approval", fontsize=11, loc="left")
a2.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c) for c in STAGES],
          labels=[f"{l}: {v:.0f} ms" for l, v in zip(labels, ms)], frameon=False, loc="upper center",
          bbox_to_anchor=(0.5, -0.18), ncol=2, fontsize=9)
a2.set_ylim(-0.6, 0.6)

fig.suptitle("Guided computer use: DeepSeek planner + GoClick on a Modal GPU, real websites",
             fontsize=12, fontweight="bold", x=0.01, ha="left")
fig.tight_layout()
out = ROOT / "benchmark" / "scorecard.png"
fig.savefig(out, dpi=130, facecolor=SURFACE)
print(out, dict(zip(labels, [round(m) for m in ms])))
