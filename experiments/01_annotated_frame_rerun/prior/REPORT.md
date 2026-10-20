> [!WARNING]
> **Auto-generated report — not the final report.** Written by DeepSeek (an AI model) while it ran
> this experiment on 2026-10-19. Kept unedited as a record; its numbers were not independently verified.
> The reviewed summary of all experiments is [`experiments/README.md`](../../README.md).

# Container recreation of the UI-detection experiment

**Date:** 2026-10-19 · **Host:** macOS 26.7.1, arm64 · **Runtime:** Apple `container` CLI 1.4.1
**Target:** a disposable Alpine Linux desktop, viewed over VNC, reached over SSH
**Model under test:** `deepseek-flash` = DeepSeek-V4.1-Flash-1017 (OpenAI-compatible API, vision enabled)

---

## 1. The container

Built from `container/Dockerfile` — Alpine 3.22 + Xorg (dummy driver) + Openbox + x11vnc + openssh + Firefox 142.
No desktop environment, no GPU, no display hardware: Xorg renders into a virtual framebuffer at 1280×800.

```
$ container list
ID        IMAGE       OS     ARCH   STATE    IP                CPUS  MEMORY
cua-ui    cua-ui:1    linux  arm64  running  192.168.64.11/24  2     2048 MB

$ container stats --no-stream cua-ui
Container ID  Cpu %  Memory Usage         Net Rx/Tx             Block I/O                Pids
cua-ui        0.13%  1.03 GiB / 2.00 GiB  33.73 MiB / 4.60 MiB  525.87 MiB / 397.69 MiB  203
```

Inside the guest:

| | |
|---|---|
| kernel | `Linux 6.18.35 aarch64` |
| distro | Alpine 3.22.7 |
| memory | 2.0 GiB (501 MiB used at idle) |
| browser | Mozilla Firefox 142.0, kiosk mode |
| X server | Xorg 1.21.1.19, 1280×800, 24-bit |
| listeners | `0.0.0.0:5900` (x11vnc), `0.0.0.0:22` (sshd), `127.0.0.1:8080` (mock site) |

**View it:** `open vnc://192.168.64.11:5900` — password `1234`
**SSH in:** `ssh -i experiment/container/id_ed25519 root@192.168.64.11`

The page is a self-contained mock booking site (`container/site/index.html`), served from inside the
container so the experiment is reproducible and does not depend on a third-party site changing.

> Note: `container run -p 5900:5900` failed with `bind: Address already in use` on this host, so the
> container is addressed directly at its vmnet IP. Publishing is optional, not required.

---

## 2. What was run

Exactly the repo's pipeline, re-pointed at the container:

```
VNC capture (vncdotool) → YOLOv8 UI detection → annotate → VLM analysis
```

Three VLM configurations, same frame, same model:

| ID | Image sent | Detection data | Mirrors |
|----|-----------|----------------|---------|
| **A1** | raw capture | flat text list, from `chunk02_best.pt` | `tests/vnc_vlm_loop.py` as published |
| **A2** | raw capture | flat text list, from `yolov8_ui_model.pt` | as published + a better model |
| **B** | **annotated** capture | **structured JSON** (id, label, conf, bbox, centre) | the proposed fix |

Thinking mode is **disabled** for all three (see §5).

---

## 3. Results

### 3.1 Detectors (same frame, 1280×800, median of 5 runs, warm)

| Model | Detections @ conf≥0.5 | Median inference | Breakdown |
|---|---|---|---|
| `yolov8_ui_model.pt` (web) | **28** | **66 ms** | button×11 (0.76), text×8 (0.72), image×4 (0.57), field×3 (0.64), heading×2 (0.66) |
| `chunk02_best.pt` (RICO mobile) | **0** | 66 ms | — (7 boxes appear only if the threshold drops to 0.15, all labelled `Misc`/`EditText`, max conf 0.42) |

**The repo's default model for the main loop detects nothing on a desktop page at the repo's own
`CONF_THRESHOLD = 0.5`.** In the published pipeline the detection list forwarded to the VLM would be
empty for every frame.

### 3.2 VLM runs

| ID | Latency | Prompt tok | Output tok | Finish | Est. cost |
|----|---------|-----------|-----------|--------|-----------|
| A1 | 6.0 s | 764 | 870 | `stop` | $0.00127 |
| A2 | 5.5 s | 1,125 | 900 | `length` (truncated) | $0.00142 |
| B | 5.0 s | 2,576 | 770 | `stop` | $0.00170 |

Cost at peak-hour Flash pricing ($0.30/1M in, $1.20/1M out). Total for the three-way comparison:
**$0.0044**. At the repo's 20 s interval that extrapolates to ≈ $0.76/hour, versus roughly $20/hour
for `gpt-4o` at the same cadence.

### 3.3 Detector score (visual benchmark, `benchmark/panel_detector.png`)

28 detections scored against 31 hand-labelled ground-truth elements (IoU ≥ 0.40, then class check):

| correct box + correct label | correct box, wrong label | duplicate / nested | false positive | missed |
|---|---|---|---|---|
| 23 | 3 | 2 | 0 | 5 |

Recall **84 %** · precision **93 %** · label accuracy **88 %**.
Missed: **Search button**, Round-trip radio, Add-hotel checkbox, **India card**, **Japan card**.
Wrong labels: `#8` From field, `#3` Travellers field and `#24` Return field all labelled `button`.

### 3.4 VLM grounding score (visual benchmark, `benchmark/panel_vlm.png`)

Each model's per-box claim was checked against the element that box actually covers:

| | Boxes addressed | Correct | Partly right | Wrong | Accuracy |
|---|---|---|---|---|---|
| A1 | 0 | — | — | — | n/a — no boxes existed |
| A2 | 13 | 1 | 0 | 12 | **8 %** |
| B | 28 | 16 | 1 | 11 | **57 %** (61 % lenient) |

A2's single correct claim was `#19` → "To field". It also invented country cards at `#16/#23/#25/#27`
and called `#3` the "Flights tab".

B's 11 errors are overwhelmingly **neighbour swaps** — the right row, one element over:
`#7` Round-trip label called "One-way", `#15` One-way called "Return", `#27` Multi-city icon called
"One-way", `#23` nearby-airports checkbox called "origin field icon". Three sit on boxes the detector
itself mislabelled (`#3`, `#18`, `#24`), which is the case where structured input amplifies the error.

> **Methodology caveat.** These are single-run samples at default sampling temperature; the exact
> score moves by a few boxes between runs (an earlier run scored B at 18/28 on a looser read). The
> audit is deliberately strict: a claim only counts if it names the element the box actually covers.

---

## 4. Findings

**1. The published pipeline never shows the VLM the boxes — and the model says so.**
A1's answer opens with: *"while the prompt mentions colored bounding boxes, the image provided does
not contain any visible colored overlays."* The annotated frame is written to `resources/output/` but
the raw capture is what gets uploaded.

**2. Without pixels, box ids are fabricated.** A2 received 28 ids as text and assigned them in reading
order: `#1` → "Flights", `#2` → "Hotels", `#6` → "Packages". In reality `#1` is *Sign in*, `#2` is
*Register*, `#6` is *Car hire*. It produced a confident, fluent, ~90 % wrong mapping — the failure mode
that is hardest to notice by eye.

**3. The fix works, but does not fully close the gap.** B referenced every id and got 16/28 strictly
correct (57 %, 61 % lenient), and it correctly flagged genuine detector faults: the missing
*India*/*Japan* cards and duplicate boxes on the *Return* field. A2, given the same detections as text
only, scored 1/13 (8 %).

**4. The VLM trusts YOLO's label over the geometry.** B called `#3` the "Search button" because the
detector tagged `#3 button 0.85` — but `#3` covers the *Travellers* field, and the real Search button has
no box at all. When the detector is wrong, structured input propagates the error rather than correcting
it. Any agent layer must treat the label as a hint and the geometry as truth.

**5. Thinking mode needs a budget, or it never answers.** With `thinking` enabled, `deepseek-flash` spent
4,000 and then 8,000 tokens on reasoning and returned **zero characters** (`finish_reason = length`),
twice. Reasoning tokens count against `max_tokens`. Disabled, the same task answers in ~5 s. The harness
now falls back automatically, but this is a trap worth documenting.

**6. Vision tokens are cheap and bounded.** 1280×800 → 688 image tokens (the API caps an image near
1024 tokens by downscaling to ≈1300×1300 equivalent), and `detail: "original"` preserved enough fidelity
to read the small box labels.

---

## 5. Notes / caveats

- `deepseek-flash` is a model *alias*: it currently resolves to DeepSeek-V4.1-Flash-1017, and legacy names
  redirect to it. Pin behaviour by recording `resp.model` (the runs logged `deepseek-flash`).
- The `thinking` parameter must be passed via `extra_body`; the OpenAI SDK rejects it as a direct kwarg.
- Detector latency of 66 ms is well below the README's claimed ~120 ms, but that is a warm median on
  Apple silicon; the first cold inference was ~7.4 s.
- VNC capture costs ~1.6 s per frame here, almost entirely `vncdotool` process startup — the README's
  "~50 ms" figure is not reproducible with this capture method.
- The mock page is not drawn from the YOLO training distribution (real web screenshots), so detector
  recall here is a lower bound on what a domain-matched dataset could reach.

---

## 6. Reproduce

```bash
cd experiment
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python \
    ultralytics opencv-python-headless pillow openai python-dotenv vncdotool

# container (needs Apple `container` services running)
container build --tag cua-ui:1 --file container/Dockerfile container
container run -d --name cua-ui -c 2 -m 2G cua-ui:1
container list                     # note the IP

VNC_TARGET=<ip>::5900 ./.venv/bin/python run_experiment.py
```

`results/` holds the raw and annotated frames, one markdown transcript per VLM variant, and
`run_log.json` with every detection, coordinate, token count and attempt.

`benchmark/` holds the visual benchmark:

| file | what it shows |
|---|---|
| `panel_ground_truth.png` | the 31 real UI elements, hand-labelled |
| `panel_detector.png` | every YOLO box coloured by outcome, missed elements in magenta |
| `panel_vlm.png` | A2 vs B, each box coloured by whether the model's claim was right |
| `scorecard.png` | the numbers behind the pictures |
| `box_table.md` | per box: what the detector said, what it covers, what A2/B claimed |
| `metrics.json` | machine-readable results |

Regenerate the benchmark with `./.venv/bin/python render_benchmark.py` after editing
`benchmark_data.py` (ground truth + hand audit).
