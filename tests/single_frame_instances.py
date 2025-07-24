import subprocess
import cv2
from PIL import Image
import numpy as np
from ultralytics import YOLO
import random


# === CONFIG ===
VNC_CLI_PATH = "/Users/tarunkashyap/Desktop/annotate/annenv/bin/vncdotool"
VNC_HOST = "localhost"
VNC_PORT = 5900
VNC_PASSWORD = "1234"
OUTPUT_FRAME = "./resources/frame.png"
CONF_THRESHOLD = 0.4
ALLOWED_CLASSES = {"button", "input", "field", "link", "text", "label", "iframe"}

# === Load Model ===
model = YOLO("./models/yolov8_ui_model.pt")

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

def get_random_color():
    return tuple(random.randint(0, 255) for _ in range(3))

# === Grab + Predict + Annotate ===
if grab_vnc_frame():
    pil_img = Image.open(OUTPUT_FRAME).convert("RGB")
    frame = np.array(pil_img)

    results = model.predict(frame, save=False)[0]

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
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, label_instance, (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    # Show annotated result
    cv2.imshow("Instance Detection", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    print("[i] Press 'q' to close the window.")
    while True:
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    cv2.destroyAllWindows()
else:
    print("[!] Could not retrieve VNC frame.")
