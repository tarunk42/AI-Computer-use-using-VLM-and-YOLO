#!/usr/bin/env python3
"""Serves the mock booking page and records the page's own state.

The page POSTs its form state to /state on every change; the agent harness reads it back
as deterministic ground truth for scoring a task (no model in the evaluation loop).
"""
import json
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

STATE_FILE = Path("/tmp/page_state.json")
_lock = threading.Lock()


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _send(self, code: int, payload: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path.startswith("/state"):
            with _lock:
                data = STATE_FILE.read_bytes() if STATE_FILE.exists() else b"{}"
            return self._send(200, data, "application/json")
        if self.path in ("/", "/index.html"):
            return self._send(200, (Path("/opt/site/index.html")).read_bytes(), "text/html")
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path.startswith("/state"):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                incoming = json.loads(body)
            except Exception:
                return self._send(400, b"bad json", "text/plain")
            with _lock:
                old = {}
                if STATE_FILE.exists():
                    try:
                        old = json.loads(STATE_FILE.read_text())
                    except Exception:
                        old = {}
                # drop stale writes: without this, a late focus-in POST can
                # overwrite a newer click result (race seen in benchmarking)
                same_session = incoming.get("session") == old.get("session")
                if same_session and int(incoming.get("seq", 0)) < int(old.get("seq", 0)):
                    return self._send(200, b'{"ok":true,"stale":true}', "application/json")
                STATE_FILE.write_bytes(body)
            return self._send(200, b'{"ok":true}', "application/json")
        return self._send(404, b"not found", "text/plain")


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8080), Handler).serve_forever()
