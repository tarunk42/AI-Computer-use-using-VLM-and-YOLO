import subprocess
import time
import cv2
from PIL import Image
import numpy as np
from ultralytics import YOLO
import random
import os
from pathlib import Path
from openai import OpenAI
import io
import base64

# CONFIG
VNC_CLI_PATH = "/Users/tarunkashyap/Desktop/annotate/annenv/bin/vncdotool"
VNC_HOST = "localhost"
VNC_PORT = 5900
VNC_PASSWORD = "1234"
OUTPUT_FRAME = "./resources/temp/frame.png"
INTERVAL = 20  # seconds
CONF_THRESHOLD = 0.5
OUTPUT_DIR = "./resources/output"

# YOLO Model
MODEL_PATH = "./models/chunk02_best.pt"
model = YOLO(MODEL_PATH)
class_names = model.names

# OpenAI API
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("OPENAI_API_KEY not found in environment. Exiting.")
    exit(1)
client = OpenAI(api_key=api_key)

def get_random_color():
    return tuple(random.randint(0, 255) for _ in range(3))

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

def prepare_image(path):
    with Image.open(path) as img:
        img = img.convert("RGB")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=70)
        return base64.b64encode(buffer.getvalue()).decode()

def run_vlm_analysis(image_path, detections_list):
    base64_image = prepare_image(image_path)
    
    # Prepare detailed prompt with detection information
    # Each entry already carries the "#<id>" drawn on its box in the image
    detection_info = "\n".join(f"- {det}" for det in detections_list)
    prompt = f"""This image has colored bounding boxes around UI elements. The detected objects are:
{detection_info}

Please analyze the UI and provide:
1. For each colored bounding box, identify the UI element type and its specific function
2. Match each detection box with its likely corresponding element in the UI (e.g., "The blue bounding box (#3) is a Search button")
3. Explain what actions a user could take with each identified element
4. Suggest a logical sequence of actions a user might perform on this screen

Focus on correlating the visible bounding boxes with their actual UI functions."""
    
    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}",
                        }
                    }
                ]
            }
        ],
        max_tokens=800
    )
    return completion.choices[0].message.content

# Ensure output dir exists
Path(OUTPUT_DIR).mkdir(exist_ok=True)

frame_count = 0

while True:
    start_time = time.time()
    frame_count += 1

    print(f"--- Frame {frame_count} ---")

    if not grab_vnc_frame():
        time.sleep(INTERVAL)
        continue

    # Load and convert image
    pil_img = Image.open(OUTPUT_FRAME).convert("RGB")
    frame = np.array(pil_img)

    # Run YOLO detection
    results = model.predict(frame, save=False)[0]

    # Annotate frame
    annotated_frame = frame.copy()
    detections = []

    for box in results.boxes:
        conf = float(box.conf[0])
        cls_id = int(box.cls[0])

        if conf < CONF_THRESHOLD:
            continue

        label = class_names[cls_id]
        det_id = len(detections) + 1
        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
        # Same "#<id>" in the text list and on the image, so the VLM can match them
        detections.append(f"#{det_id} {label} (conf: {conf:.2f}, bbox: [{x1}, {y1}, {x2}, {y2}])")

        color = get_random_color()
        cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(annotated_frame, f"#{det_id} {label} {conf:.2f}", (x1, max(12, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    # Save annotated frame
    annotated_path = Path(OUTPUT_DIR) / f"frame_{frame_count:03d}.png"
    cv2.imwrite(str(annotated_path), cv2.cvtColor(annotated_frame, cv2.COLOR_RGB2BGR))
    print(f"Saved annotated frame: {annotated_path}")

    # Run VLM analysis on the annotated frame, so it can see the numbered boxes
    print("Running VLM analysis...")
    vlm_output = run_vlm_analysis(annotated_path, detections)

    # Save VLM output
    text_path = Path(OUTPUT_DIR) / f"description_{frame_count:03d}.txt"
    with open(text_path, 'w') as f:
        f.write(f"Detections: {', '.join(detections)}\n\n")
        f.write(f"VLM Analysis:\n{vlm_output}")
    print(f"Saved description: {text_path}")

    # Wait for next cycle
    elapsed = time.time() - start_time
    time.sleep(max(0, INTERVAL - elapsed))

    print(f"Cycle {frame_count} complete. Waiting for next...")
