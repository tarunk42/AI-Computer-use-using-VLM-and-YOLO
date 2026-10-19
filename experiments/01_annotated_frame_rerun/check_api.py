#!/usr/bin/env python3
"""Smoke-test the DeepSeek API: text-only, then vision on the container screenshot."""
import os
import sys
import base64
from pathlib import Path

from dotenv import dotenv_values
from openai import OpenAI

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT.parents[1] / ".env"


def load_key() -> str:
    vals = dotenv_values(ENV_FILE)
    key = (vals.get("DEEPSEEK_API_KEY") or "").strip().strip('"').strip("'")
    if not key:
        sys.exit(f"no DEEPSEEK_API_KEY in {ENV_FILE}")
    return key


def main() -> None:
    key = load_key()
    print(f"key loaded: {key[:5]}…{key[-4:]} ({len(key)} chars)")
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com")

    print("\n--- text call ---")
    r = client.chat.completions.create(
        model="deepseek-flash",
        messages=[{"role": "user", "content": "Reply with exactly: API OK"}],
        max_tokens=16,
    )
    print("model:", r.model)
    print("text :", r.choices[0].message.content.strip())
    print("usage:", r.usage.model_dump())

    img = ROOT / "results" / "00-container-raw.png"
    print(f"\n--- vision call on {img.name} ---")
    b64 = base64.b64encode(img.read_bytes()).decode()
    r = client.chat.completions.create(
        model="deepseek-flash",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "List the text of every button you can see, comma separated. No commentary."},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "original"}},
            ],
        }],
        max_tokens=200,
    )
    print("model:", r.model)
    print("reply:", r.choices[0].message.content.strip())
    print("usage:", r.usage.model_dump())


if __name__ == "__main__":
    main()
