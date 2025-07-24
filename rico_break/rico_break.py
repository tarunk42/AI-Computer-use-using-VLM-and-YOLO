import os
import shutil
from pathlib import Path
from math import ceil

# 📁 Update these paths based on your system
input_dir = Path("~/Downloads/combined").expanduser()  # where all the .jpg and .json files are
output_dir = Path("~/Downloads/rico_chunks").expanduser()  # where you want the chunked data

# ⚙️ Configuration
chunk_size = 5000

# Collect all .jpg files (assuming each has a .json counterpart)
image_files = sorted([f for f in input_dir.iterdir() if f.suffix == ".jpg"])
total_images = len(image_files)
num_chunks = ceil(total_images / chunk_size)

print(f"Found {total_images} images. Splitting into {num_chunks} chunks...")

# Make chunks
for i in range(num_chunks):
    start = i * chunk_size
    end = min(start + chunk_size, total_images)
    chunk_images = image_files[start:end]

    chunk_dir = output_dir / f"chunk_{i+1:02}"
    img_dir = chunk_dir / "images"
    ann_dir = chunk_dir / "annotations"
    img_dir.mkdir(parents=True, exist_ok=True)
    ann_dir.mkdir(parents=True, exist_ok=True)

    for img_path in chunk_images:
        json_path = img_path.with_suffix(".json")
        shutil.copy(img_path, img_dir / img_path.name)
        if json_path.exists():
            shutil.copy(json_path, ann_dir / json_path.name)

    print(f"Chunk {i+1:02} saved with {len(chunk_images)} images.")

print("✅ Done.")
