# 03 · Locally deployed grounder

A planner (DeepSeek) plus the GoClick grounder running **locally** (CPU, then Apple GPU), driving a
**mock** flight-search page in a container.

- [REPORT_deepseek_generated.md](REPORT_deepseek_generated.md): the report DeepSeek wrote during the
  run. **Auto-generated, not the final report**; see the notice at its top.
- The reviewed successor is [`guided_agent/REPORT.md`](../../guided_agent/REPORT.md).

Kept as a record. The shared secret is read from `CUA_SHARED_SECRET`; the container's SSH keys and the
model caches were never committed.
