import subprocess
from PIL import Image

def grab_vnc_screenshot_via_cli(host="localhost", port=5900, password="1234", output="frame.png"):
    try:
        cmd = [
            "/Users/tarunkashyap/Desktop/annotate/annenv/bin/vncdotool",  # full path
            "-s", f"{host}::{port}",
            "--password", password,
            "capture", output
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return Image.open(output)
    except Exception as e:
        print(f"[!] Screenshot via vncdotool failed: {e}")
        return None

# 🔍 Run it
img = grab_vnc_screenshot_via_cli()
if img:
    img.show()
    print("[+] Screenshot captured and displayed.")
else:
    print("[!] Screenshot failed.")
