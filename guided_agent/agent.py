"""Guided computer-use agent: DeepSeek plans, GoClick (Modal GPU) grounds, a human approves.

Each step:  capture -> plan (one JSON action) -> ground (if it targets an element)
            -> PROPOSAL shown to the user -> approve / correct the point / reject with a note / stop
            -> execute -> wait for the screen to settle -> measure what changed -> next step

Differences from the earlier locally deployed grounder loop:
  * nothing runs without the user's say-so (a guided agent, not an autonomous one)
  * a malformed planner reply is retried and never costs a step
  * every action is followed by a change check; "no visible change" is fed back to the planner
  * the user can fix a wrong click point by clicking the screenshot; that correction is logged
  * real-site actions: navigate, scroll, key, type with replace/submit, ask_user
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field

import ipv4_only  # noqa: F401
import httpx
import numpy as np
from openai import OpenAI
from PIL import Image

import grounder_client

def _desktop_url() -> str:
    """DESKTOP_URL, else the current IP of the 'guided-desktop' Apple container."""
    if os.environ.get("DESKTOP_URL"):
        return os.environ["DESKTOP_URL"]
    import subprocess
    out = subprocess.run(["container", "inspect", "guided-desktop"], capture_output=True, text=True).stdout
    ip = re.findall(r'"address"\s*:\s*"(\d+\.\d+\.\d+\.\d+)', out) or re.findall(r"192\.168\.\d+\.(?!1\b)\d+", out)
    return f"http://{ip[0]}:8000"


DESKTOP = _desktop_url()
MODEL = "deepseek-flash"
W, H = 1280, 800

PLANNER = """You operate a Firefox browser on a 1280x800 Linux desktop, one action per step, for a
human who approves every action before it runs. You see only the screenshot.

Reply with ONE JSON object, no prose, no code fence. Actions:
 {"action":"click","target":"<visual description>","reason":"..."}
 {"action":"type","target":"<the input field>","text":"...","submit":true|false,"reason":"..."}
 {"action":"key","keys":"<xdotool keys, e.g. Escape, ctrl+f, Page_Down>","reason":"..."}
 {"action":"scroll","direction":"down|up","amount":1-10,"reason":"..."}
 {"action":"navigate","url":"https://...","reason":"..."}
 {"action":"wait","reason":"..."}
 {"action":"ask_user","question":"...","reason":"..."}
 {"action":"done","summary":"<what was achieved or found, with the answer if the task asked a question>"}

Rules:
- "target" is a short, unique, visual description a separate pointing model will locate:
  name the visible text and type, e.g. "the 'Search' button next to the search box",
  "the search input field at the top of the page", "the link 'Alan Turing' in the first result".
- For a link inside a longer line of text, describe ONLY the link's own (underlined/coloured)
  words, e.g. "the 'str.casefold' link", not the whole line: the pointing model aims at the
  centre of whatever you describe.
- "type" clicks the field, replaces its content and, if submit is true, presses Enter.
- Add "risk":"high" to anything that buys, pays, sends, posts, deletes, signs in, accepts terms
  or submits personal data. Never type passwords or payment details: use ask_user instead.
- Cookie banners: prefer "Reject all" / "Necessary only".
- If the last action had no visible effect, do NOT repeat it unchanged: describe the target
  differently, scroll, or use a key.
- If a page shows an error, a blank page or raw data (e.g. just "200-OK") instead of the expected
  content after two attempts, the site is probably blocking automated browsers: use ask_user,
  do not keep reloading.
- Stay on the tab that holds the task's site. Ignore extra tabs that sites open on their own
  (e.g. Skyscanner's "Hotel Deals" tabs); only switch tabs if the task needs it.
- Use "done" as soon as the task is complete; include the answer when the task asks for information."""


def _b64(png: bytes) -> str:
    return base64.b64encode(png).decode()


@dataclass
class Step:
    n: int
    action: dict
    plan_ms: float = 0
    ground: dict | None = None
    point: list | None = None
    decision: str | None = None      # approved | corrected | rejected | stopped
    note: str | None = None
    outcome: str | None = None       # executed / error text
    change: dict | None = None
    exec_ms: float = 0
    tokens: dict = field(default_factory=dict)


class Desktop:
    def __init__(self, url: str = DESKTOP):
        self.c = httpx.Client(base_url=url, timeout=30)

    def screenshot(self) -> tuple[bytes, float]:
        t0 = time.time()
        png = self.c.get("/screenshot").content
        return png, (time.time() - t0) * 1000

    def act(self, **a) -> dict:
        r = self.c.post("/act", json=a).json()
        if not r.get("ok"):
            raise RuntimeError(r.get("error"))
        return r


def screen_change(before: bytes, after: bytes, point=None) -> dict:
    """Share of pixels that changed, globally and in a 160x100 window around the point."""
    a = np.asarray(Image.open(io.BytesIO(before)).convert("L"), dtype=np.int16)
    b = np.asarray(Image.open(io.BytesIO(after)).convert("L"), dtype=np.int16)
    diff = np.abs(a - b) > 12
    out = {"global": round(float(diff.mean()), 4)}
    if point:
        x, y = point
        win = diff[max(0, y - 50):y + 50, max(0, x - 80):x + 80]
        out["local"] = round(float(win.mean()), 4) if win.size else 0.0
    out["visible"] = out["global"] > 0.002 or out.get("local", 0) > 0.01
    return out


class Session:
    """One guided task. The loop runs in a thread and blocks on the user's decision."""

    MODES = ("manual", "low", "auto")   # approve everything / auto scroll+wait / auto all but risky
    REVIEW_S = 1.2                       # an auto-approved step stays on screen this long first

    def __init__(self, task: str, max_steps: int = 25, mode: str = "manual",
                 context: dict | None = None):
        self.task, self.max_steps = task, max_steps
        self.mode = mode if mode in self.MODES else "manual"
        self.auto_since: float | None = None
        self.context = context        # previous task + outcome, for follow-ups
        self.desk = Desktop()
        key = os.environ["DEEPSEEK_API_KEY"]
        self.llm = OpenAI(api_key=key, base_url="https://api.deepseek.com",
                          http_client=httpx.Client(timeout=60))
        self.steps: list[Step] = []
        self.pending: Step | None = None
        self.pending_png: bytes | None = None
        self.status = "starting"
        self.result: str | None = None
        self.events: list[str] = []
        self._decision = threading.Event()
        self._reply: dict = {}
        self.dead: list[list[int]] = []   # click points that produced no visible change
        self.usage = {"prompt": 0, "completion": 0, "calls": 0, "retries": 0}
        self.t_start = time.time()
        self.t_end: float | None = None
        self._stop = False

    # ---- user side ------------------------------------------------------
    def decide(self, kind: str, point=None, note: str | None = None, text: str | None = None):
        self._reply = {"kind": kind, "point": point, "note": note, "text": text}
        self._decision.set()

    SENSITIVE = re.compile(r"password|passcode|otp|one.time|cvv|cvc|card number|credit card|debit card|"
                           r"bank|upi|pin\b|aadhaar|passport|ssn|pay now|place order|checkout|buy|purchase|"
                           r"book now|confirm booking|sign in|log ?in|delete|send|post|submit", re.I)

    def auto_reason(self, s: "Step") -> str | None:
        """None if this step may run without a human, else why it must wait."""
        a = s.action
        if self.mode == "manual":
            return "approval mode is 'every step'"
        if a.get("reason") == "loop guard":
            return "loop guard"
        if a["action"] == "ask_user":
            return "the agent asked you something"
        if a.get("risk") == "high":
            return "planner marked it high-risk"
        text = " ".join(str(a.get(k) or "") for k in ("target", "text", "url", "keys"))
        if self.SENSITIVE.search(text):
            return "touches something sensitive (sign-in, payment, personal data, submit/send/delete)"
        if s.ground and s.ground.get("repeat_of_dead_spot"):
            return "same spot had no effect before"
        if a["action"] in ("click", "type") and not s.point:
            return "no click point"
        if self.mode == "low" and a["action"] not in ("scroll", "wait"):
            return "auto mode covers scroll/wait only"
        return None

    def request_stop(self):
        """Stop at any time: unblocks a pending decision and is checked between every stage.
        A planner or grounder call already in flight finishes first (at most a few seconds)."""
        self._stop = True
        self._reply = {"kind": "stop"}
        self._decision.set()

    def _halt(self) -> bool:
        if self._stop and self.status not in ("done", "stopped", "error"):
            self.status, self.result = "stopped", "stopped by user"
            self.log("stopped by user")
        return self._stop

    def log(self, msg: str):
        self.events.append(f"{time.strftime('%H:%M:%S')}  {msg}")

    # ---- planner --------------------------------------------------------
    def _history(self) -> str:
        if not self.steps:
            return "(none yet)"
        lines = []
        for s in self.steps[-12:]:
            a = s.action
            desc = a.get("action", "?")
            for k in ("target", "text", "keys", "url", "direction", "question"):
                if a.get(k):
                    desc += f" {k}={a[k]!r}"
            res = s.outcome or s.decision
            if s.decision == "rejected":
                res = f"REJECTED by user: {s.note or 'no reason given'}"
            elif s.change is not None:
                res += "; screen changed" if s.change["visible"] else "; NO VISIBLE CHANGE"
            if s.decision == "corrected":
                res += " (user corrected the click point)"
            if s.note and s.decision != "rejected":
                res += f"; user said: {s.note}"
            lines.append(f"{s.n}. {desc} -> {res}")
        if self.dead:
            spots = ", ".join(f"({x},{y})" for x, y in self.dead[-4:])
            lines.append(f"WARNING: clicks at {spots} had NO effect. The pointing model returns these spots "
                         "for your descriptions. Do not target them again: describe a different, shorter visible "
                         "text, or use key/scroll/navigate instead.")
        return "\n".join(lines)

    def _context_text(self) -> str:
        c = self.context
        if not c:
            return ""
        return (f"PREVIOUS TASK (this is a follow-up to it, on the same screen): {c['task']}\n"
                f"Its outcome ({c['status']}): {c.get('result') or '-'}\n"
                f"Its steps:\n{c['history']}\n\n")

    @staticmethod
    def _sig(a: dict):
        k = a.get("action")
        if k == "navigate":
            return ("navigate to", (a.get("url") or "").split("?")[0].rstrip("/"))
        if k in ("click", "type"):
            return (k, re.sub(r"\W+", " ", (a.get("target") or "").lower()).strip())
        return None

    def near_dead(self, p) -> bool:
        return bool(p) and any(abs(p[0] - x) <= 20 and abs(p[1] - y) <= 20 for x, y in self.dead)

    def plan(self, png: bytes) -> tuple[dict, float, dict]:
        msgs = [{"role": "system", "content": PLANNER},
                {"role": "user", "content": [
                    {"type": "text", "text": f"{self._context_text()}TASK: {self.task}\n\nSTEPS SO FAR:\n{self._history()}\n\n"
                                             "Current screenshot attached. Next action as one JSON object."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_b64(png)}"}}]}]
        t0 = time.time()
        for attempt in range(3):          # malformed replies are retried, never counted as steps
            r = self.llm.chat.completions.create(
                model=MODEL, messages=msgs, max_tokens=300, temperature=0,
                extra_body={"thinking": {"type": "disabled"}})
            self.usage["calls"] += 1
            self.usage["prompt"] += r.usage.prompt_tokens
            self.usage["completion"] += r.usage.completion_tokens
            text = (r.choices[0].message.content or "").strip()
            m = re.search(r"\{.*\}", text, re.S)
            try:
                a = json.loads(m.group(0)) if m else None
            except json.JSONDecodeError:
                a = None
            if a and a.get("action"):
                return a, (time.time() - t0) * 1000, {"attempts": attempt + 1}
            self.usage["retries"] += 1
            msgs += [{"role": "assistant", "content": text or "(empty)"},
                     {"role": "user", "content": "That was not a single valid JSON action. Reply with the JSON object only."}]
        return {"action": "ask_user", "question": "The planner failed to produce a valid action 3 times. What should I do?"}, \
            (time.time() - t0) * 1000, {"attempts": 3}

    # ---- execution ------------------------------------------------------
    def execute(self, s: Step):
        a, t0 = s.action, time.time()
        kind = a["action"]
        if kind == "click":
            self.desk.act(action="click", x=s.point[0], y=s.point[1])
        elif kind == "type":
            self.desk.act(action="click", x=s.point[0], y=s.point[1])
            time.sleep(0.15)
            self.desk.act(action="key", keys="ctrl+a")
            self.desk.act(action="type", text=str(a.get("text", "")))
            if a.get("submit"):
                self.desk.act(action="key", keys="Return")
        elif kind == "key":
            self.desk.act(action="key", keys=a["keys"])
        elif kind == "scroll":
            n = max(1, min(10, int(a.get("amount", 5))))
            self.desk.act(action="scroll", dy=n if a.get("direction", "down") == "down" else -n, x=640, y=450)
        elif kind == "navigate":
            self.desk.act(action="navigate", url=a["url"])
        elif kind == "wait":
            time.sleep(1.5)
        s.exec_ms = round((time.time() - t0) * 1000, 1)

    def settle(self, before: bytes, timeout: float = 4.0) -> bytes:
        """Wait until two consecutive screenshots match (page done loading), up to timeout."""
        time.sleep(0.35)
        prev, _ = self.desk.screenshot()
        end = time.time() + timeout
        while time.time() < end:
            time.sleep(0.35)
            cur, _ = self.desk.screenshot()
            if screen_change(prev, cur)["global"] < 0.001:
                return cur
            prev = cur
        return prev

    def _keepalive(self):
        """Tiny grounder call every 2.5 s while the session is open.

        Measured: after >=5 s without a request, Modal adds ~1.5 s to the next call even with the
        container still up (HTTP/1.1 and HTTP/2 alike). A guided session always idles while the
        user decides, so without this almost every step paid it. The first ping also absorbs the
        GPU cold start while the planner is thinking. Stops when the task ends, so the container
        still scales down after its 120 s idle window.
        """
        while self.status not in ("done", "stopped", "error"):
            try:
                grounder_client.warm()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2.5)

    # ---- loop -----------------------------------------------------------
    def run(self):
        try:
            self._run()
        except Exception as e:  # noqa: BLE001
            self.status, self.result = "error", f"{type(e).__name__}: {e}"
            self.log(f"error: {self.result}")
        finally:
            self.t_end = time.time()

    def _run(self):
        self.log(f"task: {self.task}")
        threading.Thread(target=self._keepalive, daemon=True).start()
        for n in range(1, self.max_steps + 1):
            if self._halt():
                return
            self.status = "planning"
            png, cap_ms = self.desk.screenshot()
            action, plan_ms, meta = self.plan(png)
            if self._halt():
                return
            s = Step(n=n, action=action, plan_ms=round(plan_ms))
            s.tokens = meta

            if action["action"] == "done":
                s.decision, s.outcome = "done", "done"
                self.steps.append(s)
                self.status, self.result = "done", action.get("summary", "")
                self.log(f"done: {self.result}")
                return

            sig = self._sig(action)
            repeats = sum(1 for p in self.steps if self._sig(p.action) == sig)
            if sig and repeats >= 2:            # third identical attempt: hand it to the human
                self.log(f"step {n}: loop guard - {sig[0]} {sig[1]!r} proposed {repeats + 1} times")
                action = {"action": "ask_user", "question":
                          f"I've tried to {sig[0]} {sig[1]!r} {repeats} times already without getting further. "
                          "The site may be blocking automated browsers. Should I try something else, or stop?",
                          "reason": "loop guard"}
                s.action = action

            if action["action"] in ("click", "type"):
                self.status = "grounding"
                g = grounder_client.ground(png, [action.get("target", "")])
                r = g["results"][0]
                s.ground = {"rtt_ms": g["rtt_ms"], "gpu_ms": g["gpu_ms"], "network_ms": g["network_ms"],
                            "cold": g["cold"], "gpu": g["gpu"], "raw": r["raw"]}
                s.point = r["point"]
                s.ground["repeat_of_dead_spot"] = self.near_dead(s.point)
                if self._halt():
                    return

            # ---- the human gate ------------------------------------------
            # The mode can change while we wait (the UI toggle), so it is re-read every 0.2 s.
            self.pending, self.pending_png = s, png
            self.status = "awaiting_user"
            self._decision.clear()
            self.auto_since = None
            while not self._decision.wait(0.2):
                if self.auto_reason(s) is None:
                    self.auto_since = self.auto_since or time.time()
                    if time.time() - self.auto_since >= self.REVIEW_S:
                        self._reply = {"kind": "approve", "auto": True}
                        break
                else:
                    self.auto_since = None
            reply, self.pending, self.auto_since = self._reply, None, None

            kind = reply["kind"]
            if kind == "stop":
                s.decision = "stopped"
                self.steps.append(s)
                self._stop = True
                self._halt()
                return
            if kind == "reject":
                s.decision, s.note = "rejected", reply.get("note")
                self.steps.append(s)
                self.log(f"step {n}: rejected ({s.note or '-'})")
                continue
            if action["action"] == "ask_user":
                s.decision, s.note, s.outcome = "answered", reply.get("note") or reply.get("text"), "answered"
                self.steps.append(s)
                self.log(f"step {n}: user answered: {s.note}")
                continue
            if reply.get("point"):
                s.point, s.decision = [int(reply["point"][0]), int(reply["point"][1])], "corrected"
            else:
                s.decision = "auto-approved" if reply.get("auto") else "approved"
            if reply.get("text") is not None and action["action"] == "type":
                action["text"] = reply["text"]
            s.note = reply.get("note")
            if action["action"] in ("click", "type") and not s.point:
                s.outcome = "no point to click"
                self.steps.append(s)
                continue

            if self._halt():
                return
            self.status = "acting"
            try:
                self.execute(s)
                s.outcome = "executed"
            except Exception as e:  # noqa: BLE001
                s.outcome = f"error: {e}"
            after = self.settle(png)
            s.change = screen_change(png, after, s.point)
            if action["action"] == "click" and not s.change["visible"] and s.point:
                self.dead.append(list(s.point))
            self.steps.append(s)
            self.log(f"step {n}: {action['action']} {action.get('target') or action.get('url') or action.get('keys') or ''}"
                     f" -> {s.outcome}, {'changed' if s.change['visible'] else 'NO CHANGE'}"
                     f" (plan {s.plan_ms} ms, ground {s.ground['rtt_ms'] if s.ground else '-'} ms)")
        self.status, self.result = "stopped", f"step limit ({self.max_steps}) reached"

    # ---- serialisation for the UI / logs ---------------------------------
    def snapshot(self) -> dict:
        p = self.pending
        return {
            "task": self.task, "status": self.status, "result": self.result,
            "elapsed_s": round((self.t_end or time.time()) - self.t_start, 1), "usage": self.usage,
            "mode": self.mode,
            "pending": None if not p else {"n": p.n, "action": p.action, "point": p.point,
                                           "plan_ms": p.plan_ms, "ground": p.ground,
                                           "hold": self.auto_reason(p),
                                           "auto_in": None if not self.auto_since else
                                           round(max(0.0, self.REVIEW_S - (time.time() - self.auto_since)), 1)},
            "steps": [s.__dict__ for s in self.steps],
            "events": self.events[-60:],
        }
