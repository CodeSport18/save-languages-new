"""
Generate Level 1 Chapter 1 (Common Fruits) slide images via Gemini image generation.
Reads the API key from google_gemini_api_key.txt in this directory.
Writes slide_01.png … slide_11.png into this directory.
"""
from __future__ import annotations

import os
import time
from io import BytesIO
from pathlib import Path

from google import genai
from google.genai import types
from google.genai.errors import ClientError
from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parent
# API_KEY_FILE = SCRIPT_DIR / "google_gemini_api_key.txt"

MODEL_ID = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image-preview")

# Level 1, Chapter 1: Common Fruits — image prompts per slide
SLIDE_PROMPTS: list[tuple[int, str]] = [
    (
        1,
        "A single bright red apple on a clean white background, photorealistic, studio lighting, centered composition",
    )
]


# def load_api_key() -> str:
#     if not API_KEY_FILE.is_file():
#         raise FileNotFoundError(f"Missing API key file: {API_KEY_FILE}")
#     key = API_KEY_FILE.read_text(encoding="utf-8").strip()
#     if not key:
#         raise ValueError(f"API key file is empty: {API_KEY_FILE}")
#     return key


def extract_first_image_bytes(response) -> bytes | None:
    if not response.candidates:
        return None
    for part in response.candidates[0].content.parts:
        if part.inline_data is not None and part.inline_data.data:
            return part.inline_data.data
    return None


def generate_one(client: genai.Client, prompt: str) -> bytes:
    last_err: Exception | None = None
    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                ),
            )
            break
        except ClientError as e:
            last_err = e
            if getattr(e, "status_code", None) == 429 and attempt < 4:
                wait = 45 * (attempt + 1)
                print(f"  Rate limited; waiting {wait}s before retry…")
                time.sleep(wait)
            else:
                raise
    else:
        raise last_err  # type: ignore[misc]

    data = extract_first_image_bytes(response)
    if data is None:
        finish = getattr(response.candidates[0], "finish_reason", None) if response.candidates else None
        raise RuntimeError(f"No image in response (finish_reason={finish}). Prompt may have been blocked.")
    return data


def main() -> None:
    # api_key = load_api_key()
    # client = genai.Client(api_key='AIzaSyDeGBRjZWJ23lSsxKufaw7JjLlcv8wzNwk'
    client = genai.Client(api_key='AIzaSyCu7lZx9v6nhp6t9WkhJH8eUZ5mVnxGJhE')
    

    for slide_num, prompt in SLIDE_PROMPTS:
        out_path = SCRIPT_DIR / f"slide_{slide_num:02d}.png"
        print(f"Generating slide {slide_num:02d}…")
        image_bytes = generate_one(client, prompt)
        Image.open(BytesIO(image_bytes)).save(out_path, format="PNG")
        print(f"  Saved {out_path.name}")
        time.sleep(1.5)

    print("Done.")


if __name__ == "__main__":
    main()
