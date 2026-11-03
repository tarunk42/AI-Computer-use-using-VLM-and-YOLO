# Changelog

## Unreleased — 2026-11-03
- Experiment 04 in `experiments/04_cloud_deployment/`: the guided agent on an AWS EC2 VM, the same
  task and grounding benchmarks, a streamed live view, a lighter Firefox, headless and full Chromium backends
  with screencast, and an HTTPS + password entry. Report with charts and screenshots.

## v2-guided-goclick — 2026-10-31
- New guided agent in `guided_agent/`: DeepSeek planner + GoClick grounder on a Modal GPU, real websites,
  web UI with approval modes, take-control, stop-anytime and loop guard.
- Experiments 01–03 added under `experiments/` with their reports.
- Decisions recorded in `docs/adr/`.

## v1-yolo-vlm — 2026-01-15
- YOLOv8 detection + VLM over a set-of-mark screenshot (`tests/vnc_vlm_loop.py`).
- Fix: the VLM now receives the annotated frame instead of the raw one.
