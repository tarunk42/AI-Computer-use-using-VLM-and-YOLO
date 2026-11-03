#!/usr/bin/env python3
"""Charts for the cloud deployment report, from the JSON files in results/.
Writes charts/backends.png and charts/tasks.png. Same style and colour order as
guided_agent/render_scorecard.py; each setup keeps one colour in every chart."""
from __future__ import annotations

import json
import statistics as st
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
RES, OUT = HERE / "results", HERE / "charts"
OUT.mkdir(exist_ok=True)

SURFACE, INK, INK2, GRID = "#fcfcfb", "#1f1f1e", "#5f5e58", "#e6e5e0"
C = {"local": "#eda100", "firefox": "#2a78d6", "shot": "#eb6834", "cast": "#1baf7a",
     "full": "#8b5cf6"}
plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "text.color": INK})


def style(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="y", length=0)


def bars(ax, labels, vals, colors, fmt, title, note):
    y = range(len(labels))[::-1]
    ax.barh(list(y), vals, color=colors, height=0.6)
    top = max(vals)
    for yi, v in zip(y, vals):
        ax.text(v + top * 0.02, yi, fmt(v), va="center", fontsize=10, color=INK)
    ax.set_yticks(list(y), labels)
    ax.set_xlim(0, top * 1.25)
    ax.set_title(title, fontsize=11, loc="left")
    ax.set_xlabel(note, fontsize=9)
    style(ax)


# --- 1. Browser backends on the VM: live view while scrolling BBC News -----------------
stream = {k: json.load(open(RES / f"stream_{k}.json")) for k in
          ("firefox_desktop", "headless_chromium", "headless_screencast",
           "full_chromium_screencast")}
names = ["Firefox desktop\n(de-bloated, uBlock)", "Headless Chromium\n(screenshots)",
         "Headless Chromium\n(screencast + ad blocking)", "Full Chromium\n(screencast + ad blocking)"]
cols = [C["firefox"], C["shot"], C["cast"], C["full"]]
ram_gb = [1.66, 1.41, 1.12, 1.21]  # `free -m` "used" right after a run (see REPORT.md §3)

fig, ax = plt.subplots(1, 3, figsize=(14, 4.4), facecolor=SURFACE, sharey=True)
bars(ax[0], names, [stream[k]["median_fps"] for k in stream], cols, lambda v: f"{v:.1f}",
     "Live-view frames per second", "higher is better")
bars(ax[1], names, [stream[k]["median_cpu_pct"] for k in stream], cols, lambda v: f"{v:.0f} %",
     "VM CPU while scrolling", "lower is better (2 vCPU)")
bars(ax[2], names, ram_gb, cols, lambda v: f"{v:.2f} GB", "VM RAM in use", "lower is better (7.6 GB)")
fig.suptitle("Browser backends on the AWS VM — scrolling BBC News, median of 3 runs",
             fontsize=12, fontweight="bold", x=0.01, ha="left")
fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig(OUT / "backends.png", dpi=130, facecolor=SURFACE)

# --- 2. End-to-end tasks: same 6 tasks x 2 runs on each setup --------------------------
runs = {"Local Mac · Firefox": ("../../guided_agent/results/tasks_v4_t4.json", C["local"]),
        "VM · Firefox desktop": ("results/tasks_vm_firefox.json", C["firefox"]),
        "VM · headless (screenshots)": ("results/tasks_vm_headless_screenshot.json", C["shot"]),
        "VM · headless (screencast)": ("results/tasks_vm_headless_screencast.json", C["cast"]),
        "VM · full Chromium (screencast)": ("results/tasks_vm_full_chromium.json", C["full"])}
labels, ok, med, cols = [], [], [], []
for name, (f, c) in runs.items():
    t = json.load(open(HERE / f))
    labels.append(name)
    ok.append(sum(r["success"] for r in t))
    med.append(st.median(r["elapsed_s"] for r in t))
    cols.append(c)

fig, ax = plt.subplots(1, 2, figsize=(12, 4.0), facecolor=SURFACE, sharey=True)
bars(ax[0], labels, ok, cols, lambda v: f"{v:.0f}/12", "Tasks answered correctly",
     "6 real-site tasks × 2 runs, every step auto-approved")
ax[0].set_xlim(0, 15)
bars(ax[1], labels, med, cols, lambda v: f"{v:.1f} s", "Median time per task",
     "lower is better; includes Modal cold starts")
fig.suptitle("End-to-end tasks — local Mac vs the AWS VM", fontsize=12, fontweight="bold",
             x=0.01, ha="left")
fig.tight_layout(rect=(0, 0, 1, 0.91))
fig.savefig(OUT / "tasks.png", dpi=130, facecolor=SURFACE)
print("wrote", *(p.name for p in OUT.glob("*.png")))
