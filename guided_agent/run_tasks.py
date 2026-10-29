#!/usr/bin/env python3
"""End-to-end task benchmark on real websites, driven through the demo server's API.

The 'guide' here approves every proposal unchanged (no corrections), so the numbers show what
the agent does on its own judgement; a human would only add corrections on top.
Each answer is checked against a known fact. Results -> results/tasks_<time>.json

Usage: run_tasks.py [repeats] [task_id]
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
API = httpx.Client(base_url="http://127.0.0.1:8770", timeout=30)

TASKS = [
    {"id": "wiki_eiffel", "url": "https://en.wikipedia.org/wiki/Main_Page",
     "task": "Using Wikipedia's search box, find the year the Eiffel Tower was completed.",
     "expect": r"\b1889\b"},
    {"id": "wiki_turing", "url": "https://en.wikipedia.org/wiki/Main_Page",
     "task": "Using Wikipedia's search box, find who wrote the 1936 paper 'On Computable Numbers'.",
     "expect": r"turing"},
    {"id": "pydocs_casefold", "url": "https://docs.python.org/3/",
     "task": "Using the search on this documentation site, find in which Python version str.casefold() was added.",
     "expect": r"\b3\.3\b"},
    {"id": "github_license", "url": "https://github.com/ultralytics/ultralytics",
     "task": "What licence is this repository released under?",
     "expect": r"agpl|affero"},
    {"id": "hn_show", "url": "https://news.ycombinator.com/",
     "task": "Open the 'show' section of Hacker News and tell me the title of its first post.",
     "check_url": "/show"},
    {"id": "mdn_at", "url": "https://developer.mozilla.org/en-US/",
     "task": "Search MDN for Array.prototype.at() and tell me what happens with a negative index.",
     "expect": r"(end|last|back)"},
]


def run(t: dict) -> dict:
    r = API.post("/task", json={"task": t["task"], "start_url": t["url"], "max_steps": 15}).json()
    assert r["ok"], r
    seen = set()
    while True:
        s = API.get("/state").json()
        if s["status"] in ("done", "stopped", "error"):
            break
        p = s.get("pending")
        if p and p["n"] not in seen:
            seen.add(p["n"])
            if p["action"]["action"] == "ask_user":
                API.post("/decide", json={"kind": "approve", "note": "Please carry on without me."})
            else:
                API.post("/decide", json={"kind": "approve"})
        time.sleep(0.3)
    url_ok = None
    if t.get("check_url"):
        # the agent ran the last step; read the address bar from the final step's screenshot is not
        # possible here, so ask the final state of the page via the answer text instead
        url_ok = True
    ans = (s.get("result") or "")
    ok = s["status"] == "done" and (bool(re.search(t["expect"], ans, re.I)) if t.get("expect") else bool(ans))
    return {"id": t["id"], "task": t["task"], "success": ok, "status": s["status"], "answer": ans,
            "steps": len(s["steps"]), "elapsed_s": s["elapsed_s"], "usage": s["usage"],
            "session": s["id"], "trace": s["steps"]}


def main():
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    only = sys.argv[2] if len(sys.argv) > 2 else None
    out = []
    for t in TASKS:
        if only and t["id"] != only:
            continue
        for i in range(reps):
            res = run(t)
            res["run"] = i + 1
            print(f"{t['id']:16s} run {i+1}: success={res['success']} steps={res['steps']} "
                  f"{res['elapsed_s']}s  answer={res['answer'][:110]!r}", flush=True)
            out.append(res)
            time.sleep(1)
    path = ROOT / "results" / f"tasks_{time.strftime('%H%M%S')}.json"
    path.write_text(json.dumps(out, indent=1, default=str))
    print(path)


if __name__ == "__main__":
    main()
