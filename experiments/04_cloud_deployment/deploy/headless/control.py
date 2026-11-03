"""Headless Chromium backend with the same HTTP API as desktop/control.py.

GET  /health
GET  /screenshot            -> PNG of the page viewport (1280x800)
POST /act {"action": ...}   -> {"ok", "ms"}
  click x y [button=1] [count=1] | move x y | type text | key keys (xdotool syntax)
  scroll dy [x y] | navigate url

No X server, window manager or browser window: the agent sees the page only (no address
bar or tabs). Playwright's sync API is not thread-safe, so one worker thread owns the
browser and HTTP handlers hand it jobs through a queue.
"""
import base64
import json
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from playwright.sync_api import sync_playwright

W, H = int(os.environ.get("W", 1280)), int(os.environ.get("H", 800))
START_URL = os.environ.get("START_URL", "https://en.wikipedia.org/wiki/Main_Page")
PORT = int(os.environ.get("PORT", 8001))
# A normal desktop Chrome user agent; the default one says "HeadlessChrome".
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/156.0.0.0 Safari/537.36")

# xdotool key names -> Playwright key names
KEYMAP = {"ctrl": "Control", "alt": "Alt", "shift": "Shift", "super": "Meta", "Return": "Enter",
          "BackSpace": "Backspace", "Escape": "Escape", "Tab": "Tab", "Delete": "Delete",
          "Home": "Home", "End": "End", "Prior": "PageUp", "Next": "PageDown",
          "Page_Up": "PageUp", "Page_Down": "PageDown", "Up": "ArrowUp", "Down": "ArrowDown",
          "Left": "ArrowLeft", "Right": "ArrowRight", "space": " "}
BUTTONS = {1: "left", 2: "middle", 3: "right"}

jobs: queue.Queue = queue.Queue()

# Common ad/tracker hosts, resolved to nowhere inside Chromium itself (no per-request
# Python callback, so page loads are not slowed). Rough equivalent of uBlock on Firefox.
AD_HOSTS = ["doubleclick.net", "googlesyndication.com", "googleadservices.com", "adservice.google.com",
            "google-analytics.com", "googletagmanager.com", "googletagservices.com",
            "amazon-adsystem.com", "adnxs.com", "criteo.com", "criteo.net", "pubmatic.com",
            "rubiconproject.com", "openx.net", "taboola.com", "outbrain.com", "scorecardresearch.com",
            "chartbeat.com", "chartbeat.net", "quantserve.com", "moatads.com", "adsrvr.org",
            "casalemedia.com", "teads.tv", "smartadserver.com", "3lift.com", "sharethrough.com",
            "indexww.com", "bidswitch.net", "yieldmo.com", "media.net", "permutive.com",
            "hotjar.com", "optimizely.com", "segment.io", "newrelic.net", "nr-data.net"]
RESOLVER = ",".join(f"MAP {h} 0.0.0.0, MAP *.{h} 0.0.0.0" for h in AD_HOSTS)

# Live view: Chromium's screencast pushes a JPEG whenever the page repaints.
frame = {"jpg": None, "n": 0}
frame_cv = threading.Condition()


def pw_key(combo: str) -> str:
    return "+".join(KEYMAP.get(p, KEYMAP.get(p.lower(), p)) for p in combo.split("+"))


def worker():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage",
                                                         f"--host-resolver-rules={RESOLVER}"])
        ctx = browser.new_context(viewport={"width": W, "height": H}, user_agent=UA,
                                  locale="en-US", reduced_motion="reduce")
        state = {"page": ctx.new_page(), "cast": None, "cast_page": None}
        # links that open a new tab: follow the newest tab, like a person would
        ctx.on("page", lambda pg: state.__setitem__("page", pg))

        def start_cast(pg):
            """(Re)start the screencast on the page the agent is looking at."""
            if state["cast"]:
                try:
                    state["cast"].detach()
                except Exception:  # noqa: BLE001
                    pass
            cdp = ctx.new_cdp_session(pg)

            def on_frame(ev):
                cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
                with frame_cv:
                    frame["jpg"] = base64.b64decode(ev["data"])
                    frame["n"] += 1
                    frame_cv.notify_all()

            cdp.on("Page.screencastFrame", on_frame)
            cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 50,
                                              "maxWidth": 960, "maxHeight": 600})
            state["cast"], state["cast_page"] = cdp, pg

        def page():
            pg = state["page"]
            if pg.is_closed():
                pg = state["page"] = ctx.pages[-1] if ctx.pages else ctx.new_page()
            if state["cast_page"] is not pg:
                start_cast(pg)
            return pg

        page().goto(START_URL, wait_until="domcontentloaded")

        def act(a):
            pg, kind = page(), a["action"]
            if kind == "click":
                pg.mouse.click(a["x"], a["y"], button=BUTTONS.get(int(a.get("button", 1)), "left"),
                               click_count=int(a.get("count", 1)), delay=40)
            elif kind == "move":
                pg.mouse.move(a["x"], a["y"])
            elif kind == "type":
                pg.keyboard.type(a["text"], delay=12)
            elif kind == "key":
                for combo in a["keys"].split():
                    if combo.lower() in ("ctrl+l", "alt+d", "f6"):  # no address bar here
                        continue
                    pg.keyboard.press(pw_key(combo))
            elif kind == "scroll":
                if "x" in a:
                    pg.mouse.move(a["x"], a["y"])
                pg.mouse.wheel(0, int(a.get("dy", 5)) * 100)  # one wheel click ~ 100 px
            elif kind == "navigate":
                url = a["url"] if "://" in a["url"] else "https://" + a["url"]
                pg.goto(url, wait_until="domcontentloaded", timeout=30000)
            else:
                raise ValueError(f"unknown action {kind}")

        while True:
            try:
                fn, arg, out = jobs.get(timeout=0.03)
            except queue.Empty:
                # Playwright only delivers events (screencast frames) while it is called,
                # so keep it ticking when there is no job.
                page().wait_for_timeout(1)
                continue
            try:
                if fn == "shot":
                    # Chromium now and then refuses a capture while the screencast runs;
                    # a retry a moment later works.
                    for attempt in range(3):
                        try:
                            png = page().screenshot(type="png", animations="allow")
                            break
                        except Exception:  # noqa: BLE001
                            if attempt == 2:
                                raise
                            page().wait_for_timeout(100)
                    out.put(("ok", png))
                else:
                    act(arg)
                    out.put(("ok", None))
            except Exception as e:  # noqa: BLE001
                out.put(("err", f"{type(e).__name__}: {e}"))


def run(fn, arg=None):
    out: queue.Queue = queue.Queue()
    jobs.put((fn, arg, out))
    return out.get(timeout=60)


class Handler(BaseHTTPRequestHandler):
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
        if self.path.startswith("/stream"):
            return self._stream()
        if self.path.startswith("/screenshot"):
            status, png = run("shot")
            return self._send(200, png, "image/png") if status == "ok" else self._send(500, {"error": png})
        self._send(404, {"error": "not found"})

    def _stream(self):
        """MJPEG of the screencast: a part per new frame, the last one resent every 2 s."""
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        seen = -1
        try:
            self.wfile.write(b"--frame\r\n")
            while True:
                with frame_cv:
                    frame_cv.wait_for(lambda: frame["n"] != seen, timeout=2)
                    jpg, seen = frame["jpg"], frame["n"]
                if jpg:
                    self.wfile.write(b"Content-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n--frame\r\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True

    def do_POST(self):
        if self.path != "/act":
            return self._send(404, {"error": "not found"})
        a = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        t0 = time.time()
        status, err = run("act", a)
        if status == "ok":
            self._send(200, {"ok": True, "ms": round((time.time() - t0) * 1000, 1)})
        else:
            self._send(400, {"ok": False, "error": err})


if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
