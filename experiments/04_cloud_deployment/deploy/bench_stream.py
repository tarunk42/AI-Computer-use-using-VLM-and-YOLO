"""Live-view benchmark on the VM: frames/s of /stream and VM CPU while scrolling a heavy page.
Runs against the web UI on 127.0.0.1:8770, whichever backend it is using.
Usage: bench_stream.py <label> [runs]"""
import json
import os
import sys
import threading
import time

import httpx

API = "http://127.0.0.1:8770"
URL = os.environ.get("BENCH_URL", "https://www.bbc.com/news")
label, runs = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 3
c = httpx.Client(timeout=60)


def cpu():
    v = list(map(int, open("/proc/stat").readline().split()[1:]))
    return v[3] + v[4], sum(v)  # idle+iowait, total


def scroll_for(sec):
    end = time.time() + sec
    while time.time() < end:
        c.post(f"{API}/manual", json={"action": "scroll", "x": 400, "y": 500, "dy": 1})
        time.sleep(0.15)


out = []
for r in range(runs):
    c.post(f"{API}/navigate", json={"url": URL})
    time.sleep(12)
    t = threading.Thread(target=scroll_for, args=(6,))
    i0, a0 = cpu()
    t.start()
    frames, t0 = 0, time.time()
    with httpx.stream("GET", f"{API}/stream", timeout=10) as s:
        for chunk in s.iter_bytes():
            frames += chunk.count(b"Content-Type: image/")
            if time.time() - t0 > 6:
                break
    t.join()
    i1, a1 = cpu()
    busy = 100 * (1 - (i1 - i0) / (a1 - a0))
    out.append({"fps": round(frames / 6, 1), "cpu_pct": round(busy)})
    print(f"{label} run {r+1}: {frames/6:.1f} frames/s, VM CPU {busy:.0f}%", flush=True)

fps = sorted(x["fps"] for x in out)[len(out) // 2]
cp = sorted(x["cpu_pct"] for x in out)[len(out) // 2]
print(f"{label} median: {fps} frames/s, VM CPU {cp}%")
json.dump({"label": label, "runs": out, "median_fps": fps, "median_cpu_pct": cp},
          open(f"results/stream_{label}.json", "w"), indent=1)
