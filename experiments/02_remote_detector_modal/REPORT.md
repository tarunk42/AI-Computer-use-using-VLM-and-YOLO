> [!WARNING]
> **Auto-generated report — not the final report.** Written by DeepSeek (an AI model) while it ran
> this experiment on 2026-10-23. Kept unedited as a record; its numbers were not independently verified.
> The reviewed summary of all experiments is [`experiments/README.md`](../README.md).

# Phase 2 — fully remote deployment (Modal + DeepSeek)

**Date:** 2026-10-23 · **Container:** `cua-ui` (Alpine 3.22, 1280×800) · **Region:** Modal `us-east`
**Goal:** move *all* compute off the host. Capture and orchestration run inside the Linux container;
detection runs on Modal; the VLM is the DeepSeek API.

A separate experiment from the local pipeline (`01_annotated_frame_rerun/`); the base code was not modified.

---

## Topology

```
┌─────────────────────────── Apple container: cua-ui ───────────────────────────┐
│  Firefox kiosk @ 1280×800                                                      │
│        │ scrot (in-container capture, 48–108 ms)                               │
│        ▼                                                                       │
│  client_incontainer.py  ──base64 PNG ~79 KB──►  Modal  detect_cpu              │
│        │                                        2 physical cores, 2 GiB      │
│        │                                        YOLOv8s, CPU-only torch       │
│        │◄─────────── detections JSON (29 boxes) ─────────────────────────────┘ │
│        ▼                                                                       │
│  Pillow annotate (in-container) ──annotated PNG──► DeepSeek api.deepseek.com   │
│                                                    deepseek-flash, thinking OFF│
└────────────────────────────────────────────────────────────────────────────────┘

The host Mac does nothing except `container exec`. No model, no capture, no inference.
```

## Deployment facts

| | |
|---|---|
| Modal app | `cua-ui-detect` (deployed in 23 s first time, 9 s on rebuild) |
| Endpoint | `https://projects-tarun97--cua-ui-detect-detect-cpu.us-east.modal.run` |
| Instance | `cpu=2`, `memory=2048`, `timeout=120`, `scaledown_window=300` |
| Image | Debian slim + CPU-only torch wheels + `opencv-python-headless` + ultralytics 8.4.193 |
| Auth | shared secret in a Modal Secret (`cua-detect-auth`), checked per request; not the CLI token |
| Model | `yolov8_ui_model.pt`, 21 MB, shipped into the image via `add_local_file` |

Secrets reach the container only as environment variables through `container exec --env-file`;
nothing is baked into the image and nothing is written to disk inside the guest.

---

## Results

### Detection is not the bottleneck

| Phase | Cold (after scale-to-zero) | Warm (median of 7) |
|---|---|---|
| In-container capture (`scrot`) | 48–108 ms | same |
| **Modal round trip (wall)** | **13.78 s** | **1.74 s** |
| — network / queue / edge | 6.2 s | **1.64 s (94 %)** |
| — server total | 7.63 s | 91 ms |
| —— of which inference | 3.45 s | **73 ms** |
| —— of which decode + model load | 4.2 s | 18 ms |
| Detections returned | 29 | 29 (identical, deterministic) |
| DeepSeek call | — | 7.3 s, 2,260 in / 1,128 out, `finish=stop` |

**94 % of the warm round trip is network, not compute.** Inference is 73 ms — statistically
indistinguishable from the 66 ms we measured locally on the Mac. Moving the detector to a datacentre
bought nothing and cost 1.6 s.

### The container is not the problem either

Same endpoint, same payload, called from the host Mac instead:

| Caller | Median wall |
|---|---|
| Host Mac | **1,643 ms** |
| Inside the container | **1,737 ms** |

A ~90 ms difference. The in-container client — inside a VM, behind NAT, in a different network
namespace — adds almost nothing. The 1.6 s is Modal's edge + single-threaded container queueing.

### Cold start is the real tax

13.8 s to first response on a fresh container: ~6 s of boot/queue plus ~7.6 s inside the function,
dominated by importing torch and loading the 21 MB checkpoint (4.2 s) and the first inference (3.45 s).
With `scaledown_window=300`, any 5-minute gap in traffic pays this again. For a 20 s capture loop that
is survivable; for an interactive agent it is not, and it is the argument for `min_containers=1`
(which trades the cold start for idle billing).

### Cost

| Config | $/s | $/hr | vs CPU |
|---|---|---|---|
| `cpu=2`, 2 GiB | 0.00003064 | **0.110** | 1.0× |
| T4, 2 cores, 4 GiB | 0.00019908 | 0.717 | **6.5×** |

Detection on Modal CPU costs roughly **$0.03 per 1,000 frames**. The VLM, at ~$0.0017/frame, is
**~55× more expensive** than the detector. Optimising detection compute is rounding error.

### The GPU verdict, by arithmetic

A T4 would take inference from ~73 ms to perhaps 15–20 ms. Against a 1,737 ms round trip that is a
**3 % end-to-end improvement for 6.5× the price**. The GPU endpoint is implemented and one env var
away (`MODAL_INCLUDE_GPU=1`), but deploying it would be spending money to confirm a subtraction.
Strictly not worth it at batch=1 — it would only start to matter with batched screenshots or a much
larger model.

### The biggest win was not the cloud

`scrot` inside the container captures in **48–108 ms**. The `vncdotool` subprocess the original repo
used took **~1,600 ms** — a VNC connect, auth, and full framebuffer read per frame. Capturing where
the pixels already are is ~20× faster than capturing them over the network, and it is the single
largest latency improvement in either experiment.

---

## Three real gotchas (all cost a redeploy)

1. **`@modal.fastapi_endpoint` requires FastAPI in the image** as of modal 1.6.3 — it is no longer
   injected. Symptom: a build-time error, not a runtime one.
2. **`opencv-python` needs `libGL.so.1`**, absent on `debian_slim`. `apt_install("libgl1")` did not
   take effect in this build; the reliable fix was uninstalling `opencv-python` and installing
   `opencv-python-headless` via `run_commands`. Headless is also ~40 MB lighter.
3. **Modal proxy-auth tokens are not the CLI token** in `~/.modal.toml`. `requires_proxy_auth=True`
   returns `401 invalid credentials` for CLI tokens. Used a Modal Secret + per-request shared secret
   instead, which is CLI-manageable end to end.

---

## Caveats

- **One frame, one seed.** 29 detections were identical across all 10 calls (deterministic), but that
  is still a single screenshot. Latency numbers are 8 samples — enough for a median, not for a tail.
- **Nothing about accuracy changed**, as expected: same weights, same pixels. 29 boxes here vs 28 in
  the local run is a different capture of the same page, not a different model.
- **`us-east` from India.** The 1.6 s round trip is largely geography plus a cold-ish edge; a
  same-region caller would see much less. The host-vs-container comparison shows the shape of it, not
  a global constant.
- **Capture is still local.** The framebuffer lives in a VM on the Mac. What moved off-host is compute
  only — so this validates "serverless inference", not "runs on a remote machine".

---

## Reproduce

```bash
cd experiments/02_remote_detector_modal
modal secret create cua-detect-auth CUA_SHARED_SECRET=$(openssl rand -hex 24)
./.venv/bin/modal deploy modal_app.py
MODAL_URL=<printed-url> N_CALLS=8 ./run_from_container.sh
```

Artifacts: `results/run_modal.json`, `results/cold_start.json`, `results/annotated.png` (drawn inside
the container), `results/vlm.md`.
