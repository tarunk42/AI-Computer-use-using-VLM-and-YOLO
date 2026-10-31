# ADR 0001: Replace YOLO + set-of-mark with a planner + grounder

**Status:** accepted · 2026-10-26

**Context.** The fine-tuned YOLO detectors missed or mislabelled many web elements, and the VLM could
only choose among what was detected (experiment 01).

**Decision.** A text/vision planner (DeepSeek, thinking off) decides the next action and describes its
target in words; a grounding model (GoClick-Base) turns the description into a pixel.

**Consequences.** No detector to train; any visible element can be targeted. The grounder points at the
centre of what is described, so the planner must describe only the clickable part (see the guided
agent report). The YOLO pipeline stays on `legacy-bug-fix` and under tag `v1-yolo-vlm`.
