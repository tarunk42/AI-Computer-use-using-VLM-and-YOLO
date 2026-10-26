#!/usr/bin/env python3
"""Local grounder benchmark: prompt -> plan -> ground -> act, scored deterministically.

Success is read from the page's own state endpoint, never from a model's opinion.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import agent
import container_io as cio

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "results"
OUT.mkdir(exist_ok=True)

# element boxes on the task page, for scoring where the grounder landed
ELEMENTS = {
    "Flights tab": [180, 10, 275, 49], "Hotels tab": [281, 11, 375, 48],
    "Car hire tab": [383, 11, 486, 49], "Packages tab": [495, 10, 613, 49],
    "Register": [1047, 11, 1150, 48], "Sign in": [1163, 12, 1252, 49],
    "Round-trip radio": [46, 262, 145, 280], "One-way radio": [160, 261, 250, 280],
    "Multi-city radio": [269, 261, 360, 279],
    "From field": [34, 292, 249, 345], "To field": [257, 292, 459, 345],
    "Depart field": [467, 291, 670, 344], "Return field": [682, 290, 883, 345],
    "Travellers field": [886, 289, 1090, 345], "Search button": [1103, 289, 1234, 346],
    "Nearby checkbox": [43, 356, 210, 376], "Direct checkbox": [232, 356, 384, 375],
    "Hotel checkbox": [429, 356, 513, 375],
    "India card": [29, 469, 319, 601], "Japan card": [345, 469, 629, 601],
    "Spain card": [655, 469, 944, 601], "Italy card": [969, 469, 1258, 601],
}

TASKS = [
    {
        "id": "T1",
        "prompt": "Search for flights to Tokyo.",
        "check": lambda s: s.get("status") == "results"
                           and "tokyo" in (s.get("to") or "").lower(),
    },
    {
        "id": "T2",
        "prompt": "Switch the trip type to one-way, then search for flights to Japan.",
        "check": lambda s: s.get("trip") == "one-way"
                           and s.get("status") == "results"
                           and "japan" in (s.get("to") or "").lower(),
    },
    {
        "id": "T3",
        "prompt": "Tick 'Add nearby airports', set the departure date to 2026-12-01, "
                  "then search for flights to Italy.",
        "check": lambda s: s.get("nearby") is True
                           and (s.get("depart") or "").strip() == "2026-12-01"
                           and s.get("status") == "results"
                           and "italy" in (s.get("to") or "").lower(),
    },
]


def hit_element(point: tuple[int, int] | None) -> str | None:
    if not point:
        return None
    x, y = point
    for name, (x1, y1, x2, y2) in ELEMENTS.items():
        if x1 <= x <= x2 and y1 <= y <= y2:
            return name
    return None


def main() -> None:
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    only = sys.argv[2] if len(sys.argv) > 2 else None

    cio.wait_boot()
    episodes = []
    for task in TASKS:
        if only and task["id"] != only:
            continue
        for r in range(repeats):
            print(f"\n=== {task['id']} run {r+1}/{repeats}: {task['prompt']}")
            ep = agent.run_episode(task["prompt"])
            ep["task_id"] = task["id"]
            ep["run"] = r + 1
            ep["success"] = bool(task["check"](ep["final_state"]))

            hits = [hit_element((s.get("ground") or {}).get("point")) for s in ep["steps"]]
            ep["ground_hits"] = hits
            ep["ground_in_element"] = sum(1 for h in hits if h)
            ep["ground_calls"] = sum(1 for s in ep["steps"] if s.get("ground"))

            if r == 0:
                png, _ = cio.capture_png()
                (OUT / f"{task['id']}_final.png").write_bytes(png)

            print(f"    success={ep['success']} steps={ep['n_steps']} "
                  f"time={ep['total_s']}s state={json.dumps(ep['final_state'])[:120]}")
            episodes.append(ep)

    # ---- summary ---------------------------------------------------------
    by_task: dict[str, list[dict]] = {}
    for e in episodes:
        by_task.setdefault(e["task_id"], []).append(e)

    summary = {"repeats": repeats, "tasks": {}, "overall": {}}
    for tid, eps in by_task.items():
        summary["tasks"][tid] = {
            "prompt": eps[0]["task"],
            "runs": len(eps),
            "successes": sum(1 for e in eps if e["success"]),
            "success_rate": round(sum(1 for e in eps if e["success"]) / len(eps), 3),
            "mean_steps": round(statistics.mean(e["n_steps"] for e in eps), 2),
            "mean_seconds": round(statistics.mean(e["total_s"] for e in eps), 1),
        }

    all_steps = [s for e in episodes for s in e["steps"]]
    plans = [s["plan_s"] for s in all_steps if s.get("plan_s")]
    grounds = [s["ground"]["infer_ms"] for s in all_steps if (s.get("ground") or {}).get("infer_ms")]
    caps = [s["capture_s"] for s in all_steps if s.get("capture_s")]
    n_ground = sum(1 for s in all_steps if s.get("ground"))
    n_hit = sum(1 for e in episodes for h in e["ground_hits"] if h)

    summary["overall"] = {
        "episodes": len(episodes),
        "successes": sum(1 for e in episodes if e["success"]),
        "success_rate": round(sum(1 for e in episodes if e["success"]) / len(episodes), 3),
        "mean_steps": round(statistics.mean(e["n_steps"] for e in episodes), 2),
        "mean_seconds": round(statistics.mean(e["total_s"] for e in episodes), 1),
        "plan_ms_median": round(statistics.median(plans) * 1000) if plans else None,
        "ground_ms_median": round(statistics.median(grounds)) if grounds else None,
        "capture_ms_median": round(statistics.median(caps) * 1000) if caps else None,
        "grounding_in_element": f"{n_hit}/{n_ground}",
        "grounding_rate": round(n_hit / n_ground, 3) if n_ground else None,
    }

    (OUT / "bench.json").write_text(json.dumps({"summary": summary, "episodes": episodes}, indent=2))
    print("\n================ PATH C SUMMARY ================")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
