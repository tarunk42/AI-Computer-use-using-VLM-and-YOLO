# ADR 0002: Run the grounder on a Modal GPU, T4 first

**Status:** accepted · 2026-10-30

**Context.** Local CPU/MPS grounding was slow and ties the agent to one machine (experiment 03).
Serverless detection already worked in experiment 02.

**Decision.** Serve GoClick from Modal, GPU list `T4 → L4 → A10G`, weights baked into the image,
token auth, 120 s idle window, keep-alive calls while a session is open, IPv4 forced on networks with
broken NAT64.

**Consequences.** ~0.1–0.16 s GPU time per target; network to `us-east` (~0.5–0.75 s) is now the larger
cost. Pay only while a session is open.
