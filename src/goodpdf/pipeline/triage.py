from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from goodpdf.pipeline.jobs import LogFn

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MIN_SIDE = 200
MIN_AREA = 50_000
DUPLICATE_WITHIN_DOC_THRESHOLD = 2
FRONT_MATTER_PAGES = {0, 1}
BACK_MATTER_HINTS = ("page_-1", "page_-2")


@dataclass(slots=True)
class TriageSummary:
    ignore: int = 0
    store_only: int = 0
    needs_llm: int = 0

    @property
    def total(self) -> int:
        return self.ignore + self.store_only + self.needs_llm


def _log(emit: LogFn | None, message: str) -> None:
    if emit is not None:
        emit(message)


def parse_page_number(filename: str) -> int | None:
    parts = filename.split("_")
    for index, part in enumerate(parts):
        if part == "page" and index + 1 < len(parts):
            try:
                return int(parts[index + 1])
            except ValueError:
                return None
    return None


def iter_images(root: Path):
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS and path.parent.name == "images":
            yield path


def document_key(root: Path, img: Path) -> str:
    return str(img.parent.parent.relative_to(root))


def build_hash_index(root: Path) -> dict[str, dict[str, int]]:
    index: dict[str, dict[str, int]] = {}
    for img in iter_images(root):
        try:
            digest = hashlib.sha256(img.read_bytes()).hexdigest()
        except OSError:
            continue
        doc_key = document_key(root, img)
        doc_counts = index.setdefault(digest, {})
        doc_counts[doc_key] = doc_counts.get(doc_key, 0) + 1
    return index


def classify(root: Path, img: Path, hash_index: dict[str, dict[str, int]]) -> tuple[str, str]:
    try:
        with Image.open(img) as pil_image:
            width, height = pil_image.size
    except (UnidentifiedImageError, OSError) as exc:
        return "ignore", f"unreadable:{exc.__class__.__name__}"

    if min(width, height) < MIN_SIDE or width * height < MIN_AREA:
        return "ignore", f"too_small:{width}x{height}"

    digest = hashlib.sha256(img.read_bytes()).hexdigest()
    doc_key = document_key(root, img)
    duplicate_count = hash_index.get(digest, {}).get(doc_key, 0)
    if duplicate_count >= DUPLICATE_WITHIN_DOC_THRESHOLD:
        return "ignore", f"duplicate_in_doc_{duplicate_count}_times"

    page = parse_page_number(img.name)
    if page is not None and page in FRONT_MATTER_PAGES:
        return "store_only", f"front_matter_page_{page}"
    if any(hint in img.name for hint in BACK_MATTER_HINTS):
        return "store_only", "back_matter"

    return "needs_llm", "substantive_candidate"


def write_sidecar(img: Path, bucket: str, reason: str) -> None:
    sidecar = img.parent.parent / f"{img.stem}.triage"
    sidecar.write_text(f"{bucket}\n{reason}\n", encoding="utf-8")


def run_triage(root: Path, emit: LogFn | None = None) -> TriageSummary:
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")

    _log(emit, f"Indexing image hashes under {root}")
    hash_index = build_hash_index(root)
    total_images = sum(1 for _ in iter_images(root))
    _log(emit, f"  {total_images} images found across the corpus")
    _log(emit, f"  {len(hash_index)} unique image hashes")

    summary = TriageSummary()
    for img in iter_images(root):
        bucket, reason = classify(root, img, hash_index)
        write_sidecar(img, bucket, reason)
        if bucket == "ignore":
            summary.ignore += 1
        elif bucket == "store_only":
            summary.store_only += 1
        else:
            summary.needs_llm += 1

    _log(
        emit,
        "Triage summary: "
        f"ignore={summary.ignore}, store_only={summary.store_only}, needs_llm={summary.needs_llm}",
    )
    return summary
