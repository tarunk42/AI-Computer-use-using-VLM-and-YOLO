# Architecture

```
 you (browser, 127.0.0.1:8770)                           Modal (us-east)
 ┌──────────────────────────┐                           ┌───────────────────────────┐
 │ live view  + click point │◄── /state, /screen.jpg ──┐ │ GoClick-Base, fp16        │
 │ Approve / Reject / Stop  │── /decide ─────────────┐ │ │ T4 (L4 fallback)          │
 └──────────────────────────┘                        │ │ │ weights baked into image  │
                                                     ▼ │ │ token auth, 120 s idle    │
 ┌──────────────── webdemo.py + agent.py (host) ───────┴─┐ └─────────────▲─────────────┘
 │ 1 screenshot ──► 2 plan (DeepSeek, JSON, no thinking)  │               │ one HTTPS call,
 │                   └─► 3 ground (if click/type) ────────┼───────────────┘ kept-alive, IPv4
 │ 4 WAIT for your decision (approve / move point / note) │
 │ 5 act ──► 6 settle (screen stops changing)             │
 │ 7 change check (global + around the point) ─► history  │
 └───────────────▲───────────────────────────────────────┘
                 │ HTTP: /screenshot, /act  (no SSH)
 ┌───────────────┴──────────────── Apple container 'guided-desktop' ┐
 │ Xvfb 1280x800 + Openbox + Firefox (real internet)                 │
 │ control.py: Pillow screen grab, xdotool click/type/key/scroll/nav │
 └───────────────────────────────────────────────────────────────────┘
```

| File | Role |
|---|---|
| `desktop/` | container image: Dockerfile, `start.sh`, `control.py`, Firefox `policies.json` |
| `grounder_modal.py` | GoClick on a Modal GPU; several targets per upload |
| `grounder_client.py` | kept-alive client, IPv4 forced, `warm()` |
| `ipv4_only.py`, `modal_cli.py` | work around this network's broken NAT64 IPv6 for Modal |
| `agent.py` | the guided loop (`Session`), planner prompt, change detection |
| `webdemo.py`, `webdemo.html` | the guided UI |
| `bench_grounding.py` | GoClick vs DOM ground truth on live sites |
| `run_tasks.py` | end-to-end real-site tasks with known answers |
| `smoke_grounder.py` | cold/warm check on the known SkyHook frame |
| `render_scorecard.py` | `benchmark/scorecard.png` |
