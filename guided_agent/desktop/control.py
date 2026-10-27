"""Desktop control server (runs inside the container).

GET  /health
GET  /screenshot            -> PNG of the whole screen
POST /act {"action": ...}   -> {"ok", "ms"}
  click        x y [button=1] [count=1]
  move         x y
  type         text           (types into whatever has focus)
  key          keys           (xdotool syntax, e.g. "ctrl+l", "Return")
  scroll       dy [x y]       (dy > 0 scrolls down, in wheel clicks)
  navigate     url            (address bar: ctrl+l, type, Return)
"""
import io
import json
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import ImageGrab


def xdo(*args):
    p = subprocess.run(["xdotool", *[str(a) for a in args]], capture_output=True, timeout=30)
    if p.returncode:
        raise RuntimeError(p.stderr.decode()[:200])


def move(x, y):
    # No --sync: xdotool's --sync waits for a motion event, and there is none when the
    # pointer is already at (x, y) - that stalled same-spot clicks for 5-18 s.
    xdo("mousemove", int(x), int(y))
    time.sleep(0.03)


def act(a):
    kind = a["action"]
    if kind == "click":
        move(a["x"], a["y"])
        xdo("click", "--repeat", int(a.get("count", 1)), "--delay", 80, int(a.get("button", 1)))
    elif kind == "move":
        move(a["x"], a["y"])
    elif kind == "type":
        xdo("type", "--delay", 12, "--", a["text"])
    elif kind == "key":
        xdo("key", "--clearmodifiers", *a["keys"].split())
    elif kind == "scroll":
        if "x" in a:
            move(a["x"], a["y"])
        dy = int(a.get("dy", 5))
        xdo("click", "--repeat", abs(dy), "--delay", 30, 5 if dy > 0 else 4)
    elif kind == "navigate":
        xdo("key", "--clearmodifiers", "ctrl+l")
        time.sleep(0.15)
        xdo("type", "--delay", 8, "--", a["url"])
        xdo("key", "Return")
    else:
        raise ValueError(f"unknown action {kind}")


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ok": True})
        if self.path.startswith("/screenshot"):
            buf = io.BytesIO()
            ImageGrab.grab(xdisplay=":0").save(buf, format="PNG", compress_level=1)
            return self._send(200, buf.getvalue(), "image/png")
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/act":
            return self._send(404, {"error": "not found"})
        try:
            a = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            t0 = time.time()
            act(a)
            self._send(200, {"ok": True, "ms": round((time.time() - t0) * 1000, 1)})
        except Exception as e:
            self._send(400, {"ok": False, "error": f"{type(e).__name__}: {e}"})


ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
