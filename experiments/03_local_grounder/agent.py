"""Local grounder agent: DeepSeek plans, GoClick grounds, xdotool acts.

The planner sees ONLY the screenshot (no DOM, no page state) - page state is used
exclusively for scoring. That keeps this a genuine vision-based computer-use loop.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path

from dotenv import dotenv_values
from openai import OpenAI

import container_io as cio

ROOT = Path(__file__).resolve().parent
ENV = ROOT.parents[1] / ".env"

DEEPSEEK_MODEL = "deepseek-flash"
GROUNDER_URL = os.environ.get("GROUNDER_URL", "http://127.0.0.1:8791/ground")
SHARED_SECRET = os.environ["CUA_SHARED_SECRET"]

PLANNER_SYSTEM = """You are controlling a Linux desktop through screenshots.
You can perform exactly one action per step:
  {"action":"click","target":"<short description of the element to click>","reason":"..."}
  {"action":"type","target":"<short description of the input field>","text":"<text to type>","reason":"..."}
  {"action":"done","reason":"..."}

Rules:
- Reply with ONE JSON object and nothing else.
- "target" must be a short visual description a grounding model can locate, e.g.
  "the search button", "the To destination input field", "the One-way radio button".
- To fill a field, use "type" with that field as target.
- Use "done" only once the task is complete.
- Never repeat an action that just failed; choose a different element description."""


def deepseek() -> OpenAI:
    key = (dotenv_values(ENV).get("DEEPSEEK_API_KEY") or "").strip().strip('"').strip("'")
    if not key:
        raise SystemExit("no DEEPSEEK_API_KEY")
    return OpenAI(api_key=key, base_url="https://api.deepseek.com")


def b64_png(png: bytes) -> str:
    return base64.b64encode(png).decode()


def plan(client: OpenAI, task: str, png: bytes, history: list[dict]) -> tuple[dict, float, dict]:
    hist = "\n".join(f"{i+1}. {h['action']} {h.get('target','')} -> {h['result']}"
                     for i, h in enumerate(history)) or "(none yet)"
    content = [
        {"type": "text", "text": f"TASK: {task}\n\nACTIONS SO FAR:\n{hist}\n\n"
                                 f"What is the single next action? Reply with one JSON object."},
        {"type": "image_url",
         "image_url": {"url": f"data:image/png;base64,{b64_png(png)}", "detail": "original"}},
    ]
    t0 = time.time()
    r = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "system", "content": PLANNER_SYSTEM},
                  {"role": "user", "content": content}],
        max_tokens=300,
        extra_body={"thinking": {"type": "disabled"}},
    )
    elapsed = time.time() - t0
    text = (r.choices[0].message.content or "").strip()
    usage = {"prompt_tokens": r.usage.prompt_tokens, "completion_tokens": r.usage.completion_tokens}

    m = re.search(r"\{.*\}", text, re.S)
    try:
        action = json.loads(m.group(0)) if m else {"action": "fail", "reason": "no json"}
    except json.JSONDecodeError:
        action = {"action": "fail", "reason": f"bad json: {text[:80]}"}
    return action, elapsed, usage


def ground(png: bytes, target: str, mode: str = "description") -> dict:
    # GoClick's template already prefixes "the"; avoid "the the search button".
    target = re.sub(r"^the\s+", "", target.strip(), flags=re.I)
    body = json.dumps({"image_b64": b64_png(png), "prompt": target,
                       "mode": mode, "token": SHARED_SECRET}).encode()
    import urllib.request
    req = urllib.request.Request(GROUNDER_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read())
    data["wall_ms"] = round((time.time() - t0) * 1000, 1)
    return data


def run_episode(task: str, max_steps: int = 6, verbose: bool = True) -> dict:
    client = deepseek()
    cio.clear_and_reload()

    history: list[dict] = []
    steps: list[dict] = []
    t_start = time.time()

    for step in range(1, max_steps + 1):
        png, cap_s = cio.capture_png()
        try:
            action, plan_s, usage = plan(client, task, png, history)
        except Exception as e:  # one retry on a transient API/capture error
            print(f"    planner error ({type(e).__name__}), retrying once")
            time.sleep(1.0)
            png, cap_s = cio.capture_png()
            action, plan_s, usage = plan(client, task, png, history)

        rec = {"step": step, "action": action.get("action"), "target": action.get("target"),
               "text": action.get("text"), "reason": action.get("reason"),
               "capture_s": round(cap_s, 2), "plan_s": round(plan_s, 2),
               "planner_tokens": usage}

        if action.get("action") == "done":
            rec["result"] = "done"
            steps.append(rec)
            break
        if action.get("action") not in ("click", "type"):
            rec["result"] = "invalid_action"
            steps.append(rec)
            history.append(rec)
            continue

        target = action.get("target") or ""
        g = ground(png, target)
        rec["ground"] = {"ok": g.get("ok"), "point": g.get("point"),
                         "infer_ms": g.get("infer_ms"), "wall_ms": g.get("wall_ms"),
                         "raw": g.get("raw")}
        if not g.get("ok") or not g.get("point"):
            rec["result"] = "ground_failed"
            steps.append(rec)
            history.append(rec)
            continue

        x, y = g["point"]
        try:
            rec["click_s"] = round(cio.click(x, y), 2)
            if action.get("action") == "type":
                rec["type_s"] = round(cio.type_text(action.get("text") or ""), 2)
            rec["result"] = "executed"
        except Exception as e:  # noqa: BLE001
            rec["result"] = f"exec_error: {e}"

        steps.append(rec)
        history.append(rec)
        if verbose:
            print(f"    step {step}: {rec['action']} '{target}' -> {rec['result']} "
                  f"@{rec['ground'].get('point') if rec.get('ground') else None} "
                  f"plan {rec['plan_s']}s ground {rec.get('ground', {}).get('infer_ms')}ms")

        time.sleep(0.8)

    final_state = cio.page_state()
    return {
        "task": task,
        "steps": steps,
        "final_state": final_state,
        "total_s": round(time.time() - t_start, 2),
        "n_steps": len(steps),
    }
