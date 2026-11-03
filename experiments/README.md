# How we got here

The repo started as YOLOv8 detection + a VLM reading a set-of-mark screenshot
(`tests/vnc_vlm_loop.py`, tag `v1-yolo-vlm`). These experiments moved it, step by step, to the
guided agent in [`guided_agent/`](../guided_agent/). Results live in each experiment's own report;
this page only tells the story and points to them.

| # | Experiment | Question | Outcome | Report |
|---|---|---|---|---|
| 01 | [Annotated-frame rerun](01_annotated_frame_rerun/) | Does the VLM do better once it actually sees the annotated frame (the `legacy-bug-fix` commit)? | Measured with and without the fix, three runs | [REPORT.md](01_annotated_frame_rerun/REPORT.md) · earlier run: [prior/REPORT.md](01_annotated_frame_rerun/prior/REPORT.md) (auto-generated) |
| 02 | [Remote detector on Modal](02_remote_detector_modal/) | Can detection move off the machine, serverless? | Detection served from Modal; latency measured | [REPORT.md](02_remote_detector_modal/REPORT.md) (auto-generated) |
| 03 | [Locally deployed grounder](03_local_grounder/) | Replace detection with a grounder (GoClick) + planner (DeepSeek)? | The pattern works on a mock page | [REPORT_deepseek_generated.md](03_local_grounder/REPORT_deepseek_generated.md) (auto-generated) |
| → | [Guided agent](../guided_agent/) | Same pattern, GoClick on a Modal GPU, real websites, human approves each step | Current system | [REPORT.md](../guided_agent/REPORT.md) |
| 04 | [Cloud deployment](04_cloud_deployment/) | Does the guided agent run the same on a small cloud VM, and can its live view keep up from far away? | Same task results; live view sped up by streaming, a lighter Firefox, and headless and full Chromium backends | [REPORT.md](04_cloud_deployment/REPORT.md) |

Reports marked *auto-generated* were written by an AI model during the run and kept unedited as
records; each carries a notice at the top. The design decisions are in [`docs/adr/`](../docs/adr/).
