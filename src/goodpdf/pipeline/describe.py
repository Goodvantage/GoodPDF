from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

from goodpdf.pipeline.jobs import LogFn

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MODEL = "gpt-4o-mini"
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2

PROMPT = """You are classifying figures from agricultural research PDFs about palm oil and sustainable farming.

Look at the image and respond with JSON in EXACTLY this shape, no other text:
{"class": "substantive" | "decorative", "description": "..."}

"substantive" means the image carries information a farmer would care about:
- chart, graph, plot, scientific figure
- map, satellite or land-use imagery
- diagram, flowchart, workflow
- annotated technical figure
- domain-relevant photo (planting, pest, disease, soil, harvest, processing, fields, machinery)
- table rendered as an image where the data matters

"decorative" means the image is visual filler with no useful content:
- logo, partner badge, organisation seal, sponsor mark
- QR code, barcode, icon
- portrait headshot of a person
- generic stock photo with no agricultural context
- repeated boilerplate (footer art, decorative banner)
- cover photo with no caption or label

For "substantive" images, "description" must be ONE concrete sentence in plain English describing what the image shows. Avoid words like "image", "figure", "shows", "depicts" — go straight to the content.

For "decorative" images, set "description" to null."""


@dataclass(slots=True)
class DescribeSummary:
    index: int = 0
    decorative_to_ignore: int = 0
    skipped: int = 0
    failed: int = 0


def _log(emit: LogFn | None, message: str) -> None:
    if emit is not None:
        emit(message)


def encode_image(path: Path) -> str:
    mime_by_suffix = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    mime = mime_by_suffix.get(path.suffix.lower(), "image/jpeg")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def call_model(client: OpenAI, image_path: Path, model: str) -> dict:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": PROMPT},
                            {"type": "image_url", "image_url": {"url": encode_image(image_path)}},
                        ],
                    }
                ],
            )
            content = response.choices[0].message.content or "{}"
            return json.loads(content)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise RuntimeError(f"model call failed after {MAX_RETRIES} attempts: {last_error}")


def read_triage(doc_folder: Path, image_stem: str) -> tuple[str, str] | None:
    sidecar = doc_folder / f"{image_stem}.triage"
    if not sidecar.is_file():
        return None
    lines = sidecar.read_text(encoding="utf-8").splitlines()
    bucket = lines[0].strip() if lines else ""
    reason = lines[1].strip() if len(lines) > 1 else ""
    return bucket, reason


def write_triage(doc_folder: Path, image_stem: str, bucket: str, reason: str) -> None:
    sidecar = doc_folder / f"{image_stem}.triage"
    sidecar.write_text(f"{bucket}\n{reason}\n", encoding="utf-8")


def write_description(doc_folder: Path, image_stem: str, description: str) -> None:
    (doc_folder / f"{image_stem}.desc").write_text(description.strip() + "\n", encoding="utf-8")


def iter_candidate_images(root: Path):
    for img in root.rglob("*"):
        if not img.is_file() or img.suffix.lower() not in IMAGE_EXTS:
            continue
        if img.parent.name != "images":
            continue
        yield img


def run_describe(
    root: Path,
    *,
    model: str = MODEL,
    api_key: str | None = None,
    api_base: str | None = None,
    emit: LogFn | None = None,
) -> DescribeSummary:
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    resolved_api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not resolved_api_key:
        raise RuntimeError("OPENAI_API_KEY env var is not set")

    client = OpenAI(api_key=resolved_api_key, base_url=api_base or None)
    summary = DescribeSummary()

    for img in iter_candidate_images(root):
        doc_folder = img.parent.parent
        stem = img.stem
        triage = read_triage(doc_folder, stem)
        if triage is None:
            summary.skipped += 1
            continue
        bucket, _ = triage
        if bucket != "needs_llm":
            summary.skipped += 1
            continue
        if (doc_folder / f"{stem}.desc").is_file():
            write_triage(doc_folder, stem, "index", "described_previously")
            summary.index += 1
            continue

        try:
            result = call_model(client, img, model)
        except Exception as exc:  # noqa: BLE001
            summary.failed += 1
            _log(emit, f"FAIL {img.relative_to(root)}: {exc}")
            continue

        image_class = (result.get("class") or "").strip().lower()
        description = (result.get("description") or "").strip() if result.get("description") else ""

        if image_class == "substantive" and description:
            write_description(doc_folder, stem, description)
            write_triage(doc_folder, stem, "index", "gpt4o_mini_substantive")
            summary.index += 1
            _log(emit, f"INDEX {img.relative_to(root)}: {description[:100]}")
        else:
            write_triage(doc_folder, stem, "ignore", "gpt4o_mini_decorative")
            summary.decorative_to_ignore += 1
            _log(emit, f"DROP  {img.relative_to(root)}")

    _log(
        emit,
        "Describe summary: "
        f"index={summary.index}, decorative_to_ignore={summary.decorative_to_ignore}, "
        f"skipped={summary.skipped}, failed={summary.failed}",
    )
    return summary
