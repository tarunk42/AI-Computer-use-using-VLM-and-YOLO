import subprocess
import cv2
from PIL import Image
import numpy as np
from ultralytics import YOLO

# === CONFIG ===
VNC_CLI_PATH = "/Users/tarunkashyap/Desktop/annotate/annenv/bin/vncdotool"
VNC_HOST = "localhost"
VNC_PORT = 5900
VNC_PASSWORD = "1234"
OUTPUT_FRAME = "frame.png"
CONF_THRESHOLD = 0.5
ALLOWED_CLASSES = {"button", "input", "field","image"}

# === Load Model ===
model = YOLO("yolov8_ui_model.pt")

def grab_vnc_frame():
    """Capture a single frame from VNC."""
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

# === Grab + Predict + Show ===
if grab_vnc_frame():
    pil_img = Image.open(OUTPUT_FRAME).convert("RGB")
    frame = np.array(pil_img)

    results = model.predict(frame, save=False)[0]

    for box in results.boxes:
        conf = float(box.conf[0])
        if conf < CONF_THRESHOLD:
            continue

        cls_id = int(box.cls[0])
        label = results.names[cls_id]

        if label not in ALLOWED_CLASSES:
            continue

        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, f'{label} {conf:.2f}', (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    cv2.imshow("YOLO Detection on VNC (Single Frame)", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    print("[i] Press 'q' to close the window.")
    while True:
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    cv2.destroyAllWindows()
else:
    print("[!] Could not retrieve VNC frame.")
