"""Cold/warm smoke test of the Modal grounder on the known SkyHook frame (6 hand-labelled targets)."""
import json, sys, time
sys.path.insert(0, '.')
import grounder_client as g
from PIL import Image
img = Image.open('../experiments/01_annotated_frame_rerun/results/run1/frames/frame_raw.png')
T = [("the Search button", [1103, 289, 1234, 346]), ("the To destination input field", [257, 292, 459, 345]),
     ("the One-way radio button", [140, 258, 250, 282]), ("the Japan destination card", [345, 469, 629, 601]),
     ("the Depart date input field", [467, 291, 670, 344]), ("the Direct flights only checkbox", [232, 356, 249, 375])]
log = []
t0 = time.time()
for i in range(4):
    d = g.ground(img, [t for t, _ in T])
    ok = sum(b[0] <= r['point'][0] <= b[2] and b[1] <= r['point'][1] <= b[3] for r, (_, b) in zip(d['results'], T) if r['point'])
    row = dict(kind="batch6", call=i, cold=d['cold'], gpu=d['gpu'], load_s=d['load_s'], rtt_ms=d['rtt_ms'],
               gpu_ms=d['gpu_ms'], per_target_ms=[r['ms'] for r in d['results']], network_ms=d['network_ms'], correct=ok)
    print(row, flush=True); log.append(row)
for i in range(10):
    d = g.ground(img, ["the Search button"])
    row = dict(kind="single", call=i, rtt_ms=d['rtt_ms'], gpu_ms=d['gpu_ms'], network_ms=d['network_ms'])
    print(row, flush=True); log.append(row)
json.dump(log, open('results/grounder_smoke.json', 'w'), indent=1)
