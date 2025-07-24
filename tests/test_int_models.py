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

# Define which class IDs to detect (from 0 to 9)
# Set to True if you want to draw that class
TARGET_CLASSES = {
    0: True,  # Button
    1: True,  # CheckBox
    2: True,  # EditText
    3: True,  # ImageButton
    4: True,  # RadioButton
    5: True,  # ToggleButton
    6: True,  # Spinner
    7: True,  # Switch
    8: True,  # SeekBar
    9: True   # Misc
}

# Load YOLO model
model = YOLO("./models/chunk02_best.pt")

# Load class names from model
class_names = model.names  # e.g., {0: 'Button', 1: 'CheckBox', ...}

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

    # Load and convert image
    pil_img = Image.open(OUTPUT_FRAME).convert("RGB")
    frame = np.array(pil_img)

    # Run detection
    results = model.predict(frame, save=False)[0]

    # Draw detections based on selected class types
    class_counts = {cls_id: 0 for cls_id in TARGET_CLASSES}

    for box in results.boxes:
        conf = float(box.conf[0])
        cls_id = int(box.cls[0])

        if conf < CONF_THRESHOLD or not TARGET_CLASSES.get(cls_id, False):
            continue

        class_counts[cls_id] += 1
        label = f"{class_names[cls_id]}: {class_counts[cls_id]}"
        color = get_random_color()

        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, label, (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    # Show the result
    cv2.imshow("YOLOv8 - UI Detection", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

    elapsed = time.time() - start_time
    time.sleep(max(0, INTERVAL - elapsed))

cv2.destroyAllWindows()
