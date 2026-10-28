"""Guided demo: http://127.0.0.1:8770

You type a task. The agent proposes one action at a time with the click point drawn on the
screen. You approve it (Enter), click the screen to correct the point, reject with a note, or stop.
Every session is saved to results/sessions/<time>.json (+ the screenshots of each proposal).
"""
from __future__ import annotations

import io
import re
import json
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from PIL import Image

import agent
import grounder_client

ROOT = Path(__file__).resolve().parent
SESS_DIR = ROOT / "results" / "sessions"
SESS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI()
# a domain or full URL with no spaces: "skyscanner.com", "https://en.wikipedia.org/wiki/X"
URL_RE = re.compile(r"^(https?://)?[\w.-]+\.[a-z]{2,}(:\d+)?(/\S*)?$", re.I)
desk = agent.Desktop()
cur: dict = {"s": None, "id": None, "mode": "manual"}


def save(s: agent.Session, sid: str):
    (SESS_DIR / f"{sid}.json").write_text(json.dumps(s.snapshot(), indent=1, default=str))


def runner(s: agent.Session, sid: str):
    s.run()
    save(s, sid)


@app.get("/", response_class=HTMLResponse)
def index():
    threading.Thread(target=grounder_client.warm, daemon=True).start()  # opening the page wakes the GPU
    return (ROOT / "webdemo.html").read_text()


@app.get("/screen.jpg")
def screen():
    png, _ = desk.screenshot()
    buf = io.BytesIO()
    Image.open(io.BytesIO(png)).convert("RGB").save(buf, format="JPEG", quality=70)
    return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/task")
def task(body: dict):
    s = cur["s"]
    if s and s.status not in ("done", "stopped", "error"):
        return {"ok": False, "error": "a task is already running"}
    url = (body.get("start_url") or "").strip()
    if url and not URL_RE.match(url):
        return {"ok": False, "error": f"Start URL doesn't look like a web address: {url[:60]!r}. "
                                      "Put instructions in the Task box."}
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    # follow-up: carry the previous task and its outcome so "now pick the cheapest" makes sense
    context = None
    prev = cur["s"]
    if body.get("follow_up") and prev:
        context = {"task": prev.task, "status": prev.status, "result": prev.result,
                   "history": prev._history()}
    sid = time.strftime("%Y%m%d-%H%M%S")
    s = agent.Session(body["task"].strip(), max_steps=int(body.get("max_steps", 25)),
                      mode=cur["mode"], context=context)
    cur.update(s=s, id=sid)
    if url:
        desk.act(action="navigate", url=url)
        time.sleep(2)
    threading.Thread(target=runner, args=(s, sid), daemon=True).start()
    return {"ok": True, "id": sid}


@app.post("/decide")
def decide(body: dict):
    s = cur["s"]
    if not s or not s.pending:
        return {"ok": False, "error": "nothing to decide"}
    s.decide(body["kind"], point=body.get("point"), note=body.get("note"), text=body.get("text"))
    return {"ok": True}


@app.post("/manual")
def manual(body: dict):
    """Direct input from the person: click / scroll / type / key, passed straight to the desktop.

    Refused while the agent is mid-step (planning, grounding, acting) so the two don't fight.
    If the agent is waiting on a proposal, that proposal is dropped (the screen it was planned
    on is about to change) and the agent re-plans, with a note that the user acted by hand."""
    s = cur["s"]
    busy = s and s.status in ("planning", "grounding", "acting", "starting")
    if busy:
        return {"ok": False, "error": f"agent is {s.status}; wait for its proposal or press Stop"}
    a = {k: body[k] for k in ("action", "x", "y", "text", "keys", "dy", "count", "button") if k in body}
    try:
        r = desk.act(**a)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    if s and s.pending:
        s.decide("reject", note="The user took over and acted by hand (screen has changed); "
                                "look at the new screenshot and continue from there.")
    if s:
        s.log(f"user (manual): {a['action']} {a.get('text') or a.get('keys') or ''}"
              f"{' @' + str([a.get('x'), a.get('y')]) if 'x' in a else ''}".rstrip())
    return r


@app.post("/mode")
def mode(body: dict):
    """Approval mode: manual (approve every step) | low (auto scroll/wait) | auto (all but risky).
    Applies to the running task immediately and to every later task."""
    m = body.get("mode")
    if m not in agent.Session.MODES:
        return {"ok": False, "error": f"mode must be one of {agent.Session.MODES}"}
    cur["mode"] = m
    if cur["s"]:
        cur["s"].mode = m
    return {"ok": True, "mode": m}


@app.post("/stop")
def stop():
    s = cur["s"]
    if not s or s.status in ("done", "stopped", "error"):
        return {"ok": False, "error": "nothing running"}
    s.request_stop()
    return {"ok": True}


@app.get("/state")
def state():
    s = cur["s"]
    if not s:
        return {"status": "idle", "mode": cur["mode"]}
    snap = s.snapshot()
    snap["id"] = cur["id"]
    return snap


@app.post("/navigate")
def navigate(body: dict):
    desk.act(action="navigate", url=body["url"])
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8770, log_level="warning")
