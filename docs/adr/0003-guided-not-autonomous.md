# ADR 0003: Guided, not autonomous

**Status:** accepted · 2026-10-31

**Decision.** Every proposed action is shown with its click point and waits for approval by default.
Approval modes (approve each / auto-scroll / auto) can relax this, but sensitive actions (log-in,
payment, sending) are always held. The agent never bypasses CAPTCHAs or bot checks; it asks the user.

**Consequences.** Slower than an autonomous agent but recoverable: the user can move a point, reject
with a note, take manual control, or stop at any time.
