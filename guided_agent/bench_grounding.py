#!/usr/bin/env python3
"""GoClick grounding accuracy on real websites, with ground truth read from the DOM.

For each page: open it in headless Chromium at 1280x800, take a screenshot, and list the
visible interactive elements (links, buttons, inputs, tabs...) with their on-screen boxes and
accessible names. Sample up to N per page, describe each the way the planner would
("the 'Log in' link", "the 'Search Wikipedia' input field"), ground them all in one call, and
score a hit when the returned point falls inside the element's box.

The DOM is used ONLY to score; GoClick sees pixels and the description.
Output: benchmark/grounding.json, benchmark/pages/<name>.png, benchmark/misses/<name>.png
"""
from __future__ import annotations

import io
import json
import math
import random
import statistics as st
import sys
import time
from pathlib import Path

import ipv4_only  # noqa: F401
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

import grounder_client

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "benchmark"
(OUT / "pages").mkdir(parents=True, exist_ok=True)
(OUT / "misses").mkdir(parents=True, exist_ok=True)

PAGES = {
    "wikipedia_main": "https://en.wikipedia.org/wiki/Main_Page",
    "wikipedia_article": "https://en.wikipedia.org/wiki/Eiffel_Tower",
    "hacker_news": "https://news.ycombinator.com/",
    "github_repo": "https://github.com/ultralytics/ultralytics",
    "python_docs": "https://docs.python.org/3/library/stdtypes.html",
    "python_org": "https://www.python.org/",
    "mdn_home": "https://developer.mozilla.org/en-US/",
    "arxiv_list": "https://arxiv.org/list/cs.CV/recent",
    "duckduckgo": "https://duckduckgo.com/",
    "openstreetmap": "https://www.openstreetmap.org/",
    "pypi_project": "https://pypi.org/project/ultralytics/",
    "huggingface_model": "https://huggingface.co/HongxinLi/GoClick-Base",
}
PER_PAGE = int(sys.argv[1]) if len(sys.argv) > 1 else 20

COLLECT = r"""
() => {
  const sel = 'a[href], button, input:not([type=hidden]), textarea, select, [role=button], [role=link], [role=tab], [role=checkbox], [role=menuitem], summary';
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8 || r.bottom <= 0 || r.right <= 0 || r.top >= innerHeight || r.left >= innerWidth) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) < 0.1) continue;
    // topmost at its centre? (skip covered elements)
    const cx = Math.min(innerWidth - 1, Math.max(0, r.left + r.width / 2)), cy = Math.min(innerHeight - 1, Math.max(0, r.top + r.height / 2));
    const top = document.elementFromPoint(cx, cy);
    if (!top || !(el === top || el.contains(top) || top.contains(el))) continue;
    const tag = el.tagName.toLowerCase(), role = el.getAttribute('role') || '';
    const type = (el.getAttribute('type') || '').toLowerCase();
    let text = (el.innerText || '').trim().replace(/\s+/g, ' ');
    const name = el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('title') ||
                 (el.querySelector('img[alt]') && el.querySelector('img[alt]').alt) || '';
    let kind;
    if (tag === 'input' && ['checkbox', 'radio'].includes(type)) kind = type;
    else if (tag === 'input' && ['submit', 'button'].includes(type)) { kind = 'button'; text = text || el.value || ''; }
    else if (['input', 'textarea'].includes(tag)) kind = 'input field';
    else if (tag === 'select') kind = 'dropdown';
    else if (tag === 'button' || role === 'button' || tag === 'summary') kind = 'button';
    else if (role === 'tab') kind = 'tab';
    else if (role === 'checkbox') kind = 'checkbox';
    else kind = 'link';
    const label = (kind === 'input field' ? (name || text) : (text || name)).trim();
    if (!label || label.length > 60) continue;
    out.push({kind, label, box: [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)]});
  }
  return out;
}
"""


def describe(e: dict) -> str:
    return f"the '{e['label']}' {e['kind']}"


def inside(p, b, pad=0):
    return b[0] - pad <= p[0] <= b[2] + pad and b[1] - pad <= p[1] <= b[3] + pad


def dist(p, b):
    dx = max(b[0] - p[0], 0, p[0] - b[2])
    dy = max(b[1] - p[1], 0, p[1] - b[3])
    return math.hypot(dx, dy)


def main():
    rng = random.Random(0)
    grounder_client.warm()
    rows, pages = [], {}
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        ctx = br.new_context(viewport={"width": 1280, "height": 800}, locale="en-US",
                             user_agent="Mozilla/5.0 (X11; Linux aarch64; rv:140.0) Gecko/20100101 Firefox/140.0")
        for name, url in PAGES.items():
            page = ctx.new_page()
            try:
                try:
                    page.goto(url, wait_until="load", timeout=45000)
                except Exception:  # noqa: BLE001  (heavy pages: settle for DOM ready)
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(3000)
                page.wait_for_timeout(1500)
                els = page.evaluate(COLLECT)
                png = page.screenshot()
            except Exception as e:  # noqa: BLE001
                print(f"{name}: load failed {e}")
                pages[name] = {"error": str(e)}
                page.close()
                continue
            page.close()
            (OUT / "pages" / f"{name}.png").write_bytes(png)
            # a label that appears on more than one interactive element (any kind) is ambiguous
            # by description alone, so it can't be scored: drop it
            counts = {}
            for e in els:
                k = e["label"].lower()
                counts[k] = counts.get(k, 0) + 1
            uniq = [e for e in els if counts[e["label"].lower()] == 1]
            sample = rng.sample(uniq, min(PER_PAGE, len(uniq)))
            if not sample:
                continue
            g = grounder_client.ground(png, [describe(e) for e in sample])
            img = Image.open(io.BytesIO(png)).convert("RGB")
            draw = ImageDraw.Draw(img)
            hits = 0
            for e, r in zip(sample, g["results"]):
                p = r["point"]
                hit = bool(p) and inside(p, e["box"])
                hits += hit
                area = (e["box"][2] - e["box"][0]) * (e["box"][3] - e["box"][1])
                rows.append({"page": name, "kind": e["kind"], "label": e["label"], "box": e["box"], "area": area,
                             "point": p, "hit": hit, "near10": bool(p) and inside(p, e["box"], 10),
                             "miss_px": round(dist(p, e["box"]), 1) if p else None, "ms": r["ms"]})
                if not hit:
                    draw.rectangle(e["box"], outline=(27, 175, 122), width=3)
                    if p:
                        draw.ellipse([p[0] - 7, p[1] - 7, p[0] + 7, p[1] + 7], outline=(235, 104, 52), width=3)
                        draw.line([p[0], p[1], (e["box"][0] + e["box"][2]) // 2, (e["box"][1] + e["box"][3]) // 2],
                                  fill=(235, 104, 52), width=2)
            img.save(OUT / "misses" / f"{name}.png")
            pages[name] = {"url": url, "candidates": len(els), "unique": len(uniq), "sampled": len(sample),
                           "hits": hits, "rtt_ms": g["rtt_ms"], "gpu_ms": g["gpu_ms"], "gpu": g["gpu"]}
            print(f"{name:18s} {hits:2d}/{len(sample):2d}  rtt {g['rtt_ms']:.0f} ms (GPU {g['gpu_ms']:.0f} ms, "
                  f"{len(sample)} targets)", flush=True)
        br.close()

    def rate(rs):
        return {"n": len(rs), "hit": round(sum(r["hit"] for r in rs) / len(rs), 3) if rs else None,
                "near10": round(sum(r["near10"] for r in rs) / len(rs), 3) if rs else None}

    by_kind = {k: rate([r for r in rows if r["kind"] == k]) for k in sorted({r["kind"] for r in rows})}
    size = {"small (<600 px²)": rate([r for r in rows if r["area"] < 600]),
            "medium (600–4000)": rate([r for r in rows if 600 <= r["area"] < 4000]),
            "large (≥4000)": rate([r for r in rows if r["area"] >= 4000])}
    miss = [r["miss_px"] for r in rows if not r["hit"] and r["miss_px"] is not None]
    summary = {"overall": rate(rows), "by_kind": by_kind, "by_size": size,
               "miss_distance_px_median": st.median(miss) if miss else None,
               "per_target_gpu_ms_median": st.median(r["ms"] for r in rows) if rows else None,
               "pages": pages}
    (OUT / "grounding.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    print(json.dumps({k: summary[k] for k in ("overall", "by_kind", "by_size", "miss_distance_px_median",
                                              "per_target_gpu_ms_median")}, indent=1))


if __name__ == "__main__":
    main()
