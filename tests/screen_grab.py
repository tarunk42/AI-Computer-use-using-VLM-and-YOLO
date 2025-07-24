import subprocess
import time
import cv2
from PIL import Image
import numpy as np
from ultralytics import YOLO
import random

def get_random_color():
    return tuple(random.randint(0, 255) for _ in range(3))

# CONFIG
VNC_CLI_PATH = "/Users/tarunkashyap/Desktop/annotate/annenv/bin/vncdotool"
VNC_HOST = "localhost"
VNC_PORT = 5900
VNC_PASSWORD = "1234"
OUTPUT_FRAME = "./resources/temp/frame.png"
INTERVAL = 2  # seconds
CONF_THRESHOLD = 0.5
ALLOWED_CLASSES = {"button"}

model = YOLO("./models/yolov8_ui_100.pt")

def grab_vnc_frame():
    try:
        subprocess.run([
            VNC_CLI_PATH,
            "-s", f"{VNC_HOST}::{VNC_PORT}",
            "--password", VNC_PASSWORD,
            "capture", OUTPUT_FRAME
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"[!] Failed to capture VNC frame: {e}")
        return False

while True:
    start_time = time.time()

    if not grab_vnc_frame():
        time.sleep(INTERVAL)
        continue

    # Load and convert image to RGB
    pil_img = Image.open(OUTPUT_FRAME).convert("RGB")
    frame = np.array(pil_img)

    # Run YOLO prediction
    results = model.predict(frame, save=False)[0]

    # Draw detections
    instance_counter = {}
    for idx, box in enumerate(results.boxes):
        conf = float(box.conf[0])
        if conf < CONF_THRESHOLD:
            continue

        cls_id = int(box.cls[0])
        label = results.names[cls_id]

        if label not in ALLOWED_CLASSES:
            continue

        # Increment instance count for label
        instance_counter[label] = instance_counter.get(label, 0) + 1
        label_instance = f"{label}: {instance_counter[label]}"

        # Draw unique color
        color = get_random_color()

        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 1)
        cv2.putText(frame, label_instance, (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    # Show in window
    cv2.imshow("YOLO Detection on VNC", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

    # Wait until next frame
    elapsed = time.time() - start_time
    time.sleep(max(0, INTERVAL - elapsed))

cv2.destroyAllWindows()
