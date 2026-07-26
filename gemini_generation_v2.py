"""
Generate lesson images with Gemini, upload them to S3, and create a lesson
in MongoDB using the `title` configured below.
"""
from __future__ import annotations

import datetime
import mimetypes
import os
import re
import time
from io import BytesIO
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pymongo import MongoClient

# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

OUTPUT_DIR = BASE_DIR / "saved_images"
IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
TEXT_MODEL = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.0-flash")

prompt_prefix = "Studio photo of "
prompt_suffix = (
    " centered. Minimalist light-grey backdrop, soft warm lighting, crisp focus, "
    "subtle floor shadows. Professional educational stock style, 1:1 aspect ratio."
)

# Lesson title used when inserting into MongoDB
title = "Emotions and Expressions"

# Set False to only generate/save images without creating a lesson
CREATE_LESSON = True


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or str(value).strip() == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def get_gemini_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key and key.strip():
        return key.strip()
    key_file = BASE_DIR / "google_gemini_api_key.txt"
    if key_file.is_file():
        key = key_file.read_text(encoding="utf-8").strip()
        if key:
            return key
    raise RuntimeError(
        "Set GEMINI_API_KEY in .env or provide google_gemini_api_key.txt"
    )


def get_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=require_env("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=require_env("AWS_SECRET_ACCESS_KEY"),
        region_name=os.environ.get("AWS_REGION", "us-east-1").strip() or "us-east-1",
    )


def get_lessons_collection():
    client = MongoClient(require_env("MONGO_URI"), tlsAllowInvalidCertificates=True)
    return client["koshur"]["lessons"]


def parse_prompts(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def generate_and_save_image(
    client: genai.Client, prompt: str, filename: str
) -> Path | None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Generating image for prompt: '{prompt}'...")

    try:
        response = client.models.generate_content(
            model=IMAGE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )

        if response.candidates:
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    img = part.as_image()
                    filepath = OUTPUT_DIR / filename
                    img.save(filepath)
                    print(f"  Success! Image saved to: {filepath}")
                    return filepath

        print("  No image was returned in the response payload.")
        return None
    except Exception as e:
        print(f"  An error occurred generating image: {e}")
        return None


def upload_image_to_s3(filepath: Path) -> str | None:
    bucket = require_env("S3_BUCKET")
    s3 = get_s3_client()
    content_type = mimetypes.guess_type(str(filepath))[0] or "image/jpeg"
    key = f"uploads/{int(time.time() * 1000)}_{filepath.name}"

    try:
        with open(filepath, "rb") as f:
            s3.upload_fileobj(
                f,
                bucket,
                key,
                ExtraArgs={"ContentType": content_type},
            )
        url = f"https://{bucket}.s3.amazonaws.com/{key}"
        print(f"  Uploaded to S3: {url}")
        return url
    except ClientError as e:
        print(f"  Failed to upload to S3: {e}")
        return None


def prompt_to_fallback_content(image_prompt: str) -> str:
    """Simple English caption from the image prompt if text generation fails."""
    text = image_prompt.strip()
    # Drop trailing style hints after the first comma cluster when useful
    text = re.sub(
        r",\s*(photorealistic|front view|side view|soft lighting|bright indoor lighting|"
        r"warm lighting|overhead angle|mirror reflection view|indoor setting).*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = text.strip(" .")
    if text and not text.endswith("."):
        text += "."
    return f"<p>{text[0].upper() + text[1:] if text else 'Look at this scene.'}</p>"


def generate_slide_content(client: genai.Client, image_prompt: str, lesson_title: str) -> str:
    """Ask Gemini for a short Kashmiri-learning caption for this slide."""
    instruction = f"""You write short slide captions for a Kashmiri language learning app.
Lesson title: {lesson_title}
Image description: {image_prompt}

Return ONLY HTML for one slide, no markdown fences. Use this exact structure:
<p><strong>English:</strong> ...simple present-tense sentence...</p>
<p><strong>Kashmiri:</strong> ...Kashmiri sentence (Perso-Arabic script if possible)...</p>
<p><em>...Latin transliteration...</em></p>
Keep it brief and educational."""

    try:
        response = client.models.generate_content(
            model=TEXT_MODEL,
            contents=instruction,
        )
        text = (response.text or "").strip()
        text = re.sub(r"^```(?:html)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        if text:
            return text
    except Exception as e:
        print(f"  Slide text generation failed, using fallback: {e}")

    return prompt_to_fallback_content(image_prompt)


def create_lesson(lesson_title: str, slides: list[dict]) -> str:
    if not slides:
        raise RuntimeError("Cannot create a lesson with no slides.")

    lessons = get_lessons_collection()
    doc = {
        "title": lesson_title,
        "slides": slides,
        "date_created": datetime.datetime.utcnow(),
        "is_slide_format": True,
    }
    result = lessons.insert_one(doc)
    lesson_id = str(result.inserted_id)
    print(f"\nLesson created: '{lesson_title}' ({len(slides)} slides)")
    print(f"  MongoDB _id: {lesson_id}")
    return lesson_id


def build_lesson_from_prompts(
    lesson_title: str,
    prompts: list[str],
    start_count: int = 1,
    create_lesson_doc: bool = True,
) -> str | None:
    api_key = get_gemini_api_key()
    client = genai.Client(api_key=api_key)

    slides: list[dict] = []
    count = start_count

    for prompt in prompts:
        full_prompt = prompt_prefix + prompt + prompt_suffix
        filename = f"{count}.jpg"
        filepath = generate_and_save_image(client, full_prompt, filename)
        if not filepath:
            count += 1
            continue

        image_url = None
        if create_lesson_doc:
            image_url = upload_image_to_s3(filepath)
            if not image_url:
                print("  Skipping slide — S3 upload failed.")
                count += 1
                continue

            content = generate_slide_content(client, prompt, lesson_title)
            slides.append(
                {
                    "content": content,
                    "image_url": image_url,
                    "audio_url": None,
                }
            )
            print(f"  Slide {len(slides)} ready.")

        count += 1
        # Small pause to reduce rate-limit pressure
        time.sleep(0.5)

    if create_lesson_doc:
        return create_lesson(lesson_title, slides)
    print(f"\nGenerated {count - start_count} image(s). Lesson creation skipped.")
    return None


if __name__ == "__main__":
    prompts = parse_prompts(
        """A close-up of a boy with a big genuine smile, photorealistic, clean background, warm lighting
A close-up of a girl with tears on her cheeks looking sad, photorealistic, clean background, soft lighting
A close-up of a man with an angry expression, furrowed brows, photorealistic, clean background
A close-up of a woman with a frightened expression, wide eyes, photorealistic, clean background
A close-up of a boy with a surprised expression, mouth open, raised eyebrows, photorealistic, clean background
A close-up of a girl with a tired expression, yawning, photorealistic, clean background
A close-up of a man with a confused expression, scratching his head, photorealistic, clean background
A close-up of a woman with a proud smile, standing tall, photorealistic, clean background
A grid of four faces showing happy, sad, angry, and surprised expressions, photorealistic, clean backgrounds"""
    )

    print(f"Lesson title: {title}")
    print(f"Prompts ({len(prompts)}):")
    for i, p in enumerate(prompts, 1):
        print(f"  {i}. {p}")

    build_lesson_from_prompts(
        lesson_title=title,
        prompts=prompts,
        start_count=20,
        create_lesson_doc=CREATE_LESSON,
    )
