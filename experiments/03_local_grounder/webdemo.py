#!/usr/bin/env python3
"""Web demo: live view of the Linux desktop + a prompt box that drives the agent.

Serves on http://127.0.0.1:8765
  GET  /            the UI
  GET  /frame.jpg   current screenshot (polled by the page)
  GET  /status      agent status, log lines, page state
  POST /task        {"task": "..."} -> starts an episode in a background thread
"""
from __future__ import annotations

import io
import json
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image

import container_io as cio

PORT = 8765
_LOCK = threading.Lock()
_STATE: dict = {
    "running": False,
    "task": None,
    "log": [],
    "started_at": None,
    "finished_at": None,
    "success": None,
    "final_state": None,
    "steps": [],
}


def log(msg: str) -> None:
    with _LOCK:
        _STATE["log"].append({"t": time.strftime("%H:%M:%S"), "msg": msg})
        _STATE["log"] = _STATE["log"][-200:]


def run_task(task: str) -> None:
    import agent

    with _LOCK:
        _STATE.update({"running": True, "task": task, "log": [], "steps": [],
                       "started_at": time.time(), "finished_at": None,
                       "success": None, "final_state": None})
    log(f"task: {task}")
    try:
        ep = agent.run_episode(task, verbose=False)
        with _LOCK:
            _STATE["steps"] = ep["steps"]
            _STATE["final_state"] = ep["final_state"]
        for s in ep["steps"]:
            pt = (s.get("ground") or {}).get("point")
            log(f"step {s['step']}: {s['action']} '{s.get('target') or ''}' "
                f"-> {s.get('result')} @ {pt}")
        with _LOCK:
            _STATE["success"] = bool(ep["final_state"].get("status") == "results")
        log(f"finished in {ep['total_s']}s - "
            f"{'SUCCESS' if _STATE['success'] else 'no results banner'}")
    except Exception as e:  # noqa: BLE001
        log(f"ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        with _LOCK:
            _STATE["running"] = False
            _STATE["finished_at"] = time.time()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, HTML.encode(), "text/html; charset=utf-8")
        if self.path.startswith("/frame.jpg"):
            try:
                png, _ = cio.capture_png()
                img = Image.open(io.BytesIO(png)).convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=75)
                return self._send(200, buf.getvalue(), "image/jpeg")
            except Exception as e:  # noqa: BLE001
                return self._send(503, str(e).encode(), "text/plain")
        if self.path.startswith("/status"):
            with _LOCK:
                snap = dict(_STATE)
            return self._send(200, json.dumps(snap).encode(), "application/json")
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path.startswith("/task"):
            n = int(self.headers.get("Content-Length", 0))
            try:
                task = json.loads(self.rfile.read(n)).get("task", "").strip()
            except Exception:
                return self._send(400, b"bad json", "application/json")
            if not task:
                return self._send(400, b'{"error":"empty task"}', "application/json")
            with _LOCK:
                busy = _STATE["running"]
            if busy:
                return self._send(409, b'{"error":"busy"}', "application/json")
            threading.Thread(target=run_task, args=(task,), daemon=True).start()
            return self._send(200, b'{"ok":true}', "application/json")
        self._send(404, b"not found", "text/plain")


HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Local grounder - Computer Use Demo</title>
<style>
 *{box-sizing:border-box} body{margin:0;background:#0b1020;color:#e5e7eb;
   font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
 header{padding:14px 20px;border-bottom:1px solid #1f2937;display:flex;
   align-items:center;gap:14px}
 h1{font-size:16px;margin:0;font-weight:600;letter-spacing:.2px}
 .pill{font-size:12px;padding:3px 10px;border-radius:999px;background:#1f2937;color:#9ca3af}
 .pill.run{background:#1e3a8a;color:#bfdbfe}
 .pill.ok{background:#14532d;color:#bbf7d0}
 .pill.bad{background:#7f1d1d;color:#fecaca}
 main{display:grid;grid-template-columns:1fr 420px;gap:16px;padding:16px;
   height:calc(100vh - 57px)}
 .screen{background:#000;border-radius:10px;overflow:hidden;display:flex;
   align-items:center;justify-content:center;border:1px solid #1f2937}
 .screen img{width:100%;height:auto;display:block}
 aside{display:flex;flex-direction:column;gap:12px;min-height:0}
 textarea{width:100%;height:84px;background:#111827;color:#e5e7eb;border:1px solid #374151;
   border-radius:8px;padding:10px;font:inherit;resize:vertical}
 button{background:#2563eb;color:#fff;border:0;border-radius:8px;padding:11px 16px;
   font-weight:600;cursor:pointer;font-size:14px}
 button:disabled{background:#374151;color:#9ca3af;cursor:not-allowed}
 .chips{display:flex;flex-wrap:wrap;gap:6px}
 .chip{font-size:12px;background:#111827;border:1px solid #374151;color:#9ca3af;
   padding:6px 9px;border-radius:999px;cursor:pointer}
 .log{flex:1;overflow:auto;background:#0f172a;border:1px solid #1f2937;border-radius:8px;
   padding:10px;font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace}
 .log div{white-space:pre-wrap}
 .t{color:#64748b}
 .state{background:#0f172a;border:1px solid #1f2937;border-radius:8px;padding:10px;
   font:11px/1.5 ui-monospace,Menlo,monospace;color:#93c5fd;max-height:150px;overflow:auto}
 label{font-size:12px;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em}
</style></head><body>
<header>
  <h1>Local grounder &mdash; prompt-driven computer use</h1>
  <span class="pill" id="pill">idle</span>
  <span class="pill" id="hint">Firefox on Alpine, 1280x800, inside Apple container</span>
</header>
<main>
  <div class="screen"><img id="view" src="/frame.jpg" alt="container desktop"></div>
  <aside>
    <label>Task</label>
    <textarea id="task">Search for flights to Tokyo.</textarea>
    <div class="chips">
      <span class="chip">Search for flights to Tokyo.</span>
      <span class="chip">Switch the trip type to one-way, then search for flights to Japan.</span>
      <span class="chip">Tick 'Add nearby airports', set the departure date to 2026-12-01, then search for flights to Italy.</span>
    </div>
    <button id="run">Run task</button>
    <label>Agent log</label>
    <div class="log" id="log"></div>
    <label>Page state (ground truth)</label>
    <div class="state" id="state">{}</div>
  </aside>
</main>
<script>
const $ = id => document.getElementById(id);
document.querySelectorAll('.chip').forEach(c => c.onclick = () => { $('task').value = c.textContent; });
let polling = true;
function tickFrame(){ if(!polling) return; $('view').src = '/frame.jpg?t=' + Date.now(); }
setInterval(tickFrame, 700);
$('view').onerror = () => setTimeout(tickFrame, 1500);

$('run').onclick = async () => {
  const task = $('task').value.trim();
  if(!task) return;
  $('run').disabled = true;
  await fetch('/task', {method:'POST', headers:{'Content-Type':'application/json'},
                        body: JSON.stringify({task})});
  $('run').disabled = false;
};

async function poll(){
  try{
    const s = await (await fetch('/status')).json();
    const pill = $('pill');
    pill.textContent = s.running ? 'running' : (s.success === true ? 'success' : s.success === false ? 'no result' : 'idle');
    pill.className = 'pill' + (s.running ? ' run' : s.success === true ? ' ok' : s.success === false ? ' bad' : '');
    $('log').innerHTML = (s.log||[]).map(l => '<div><span class="t">'+l.t+'</span>  '+l.msg+'</div>').join('');
    $('log').scrollTop = $('log').scrollHeight;
    if(s.final_state) $('state').textContent = JSON.stringify(s.final_state, null, 1);
  }catch(e){}
  setTimeout(poll, 1200);
}
poll();
</script></body></html>
"""


if __name__ == "__main__":
    print(f"[i] demo on http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
