from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from goodpdf.pipeline.jobs import LogFn

IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
EXCESS_NEWLINES = re.compile(r"\n{3,}")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


@dataclass(slots=True)
class CleanSummary:
    folders_processed: int = 0
    index: int = 0
    store_only: int = 0
    ignore: int = 0
    missing_triage: int = 0
    omitted_files: int = 0


def _log(emit: LogFn | None, message: str) -> None:
    if emit is not None:
        emit(message)


def find_markdown(doc_folder: Path) -> Path | None:
    preferred = doc_folder / f"{doc_folder.name}.md"
    if preferred.is_file():
        return preferred
    for candidate in sorted(doc_folder.iterdir()):
        if candidate.is_file() and candidate.suffix.lower() in {".md", ".markdown"}:
            return candidate
    return None


def iter_doc_folders(root: Path):
    for candidate in sorted(root.rglob("*")):
        if candidate.is_dir() and find_markdown(candidate) is not None:
            yield candidate


def read_triage(doc_folder: Path, image_stem: str) -> str | None:
    sidecar = doc_folder / f"{image_stem}.triage"
    if not sidecar.is_file():
        return None
    first_line = sidecar.read_text(encoding="utf-8").splitlines()[:1]
    return first_line[0].strip() if first_line else None


def read_description(doc_folder: Path, image_stem: str) -> str:
    desc = doc_folder / f"{image_stem}.desc"
    if not desc.is_file():
        return ""
    return desc.read_text(encoding="utf-8").strip()


def copy_kept_images(source_doc_folder: Path, output_doc_folder: Path) -> int:
    images_dir = source_doc_folder / "images"
    output_images_dir = output_doc_folder / "images"
    omitted_files = 0
    kept_files = 0

    if not images_dir.is_dir():
        return omitted_files

    for img in sorted(images_dir.iterdir()):
        if not img.is_file() or img.suffix.lower() not in IMAGE_EXTS:
            continue
        bucket = read_triage(source_doc_folder, img.stem)
        if bucket == "ignore":
            omitted_files += 1
            continue
        output_images_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(img, output_images_dir / img.name)
        kept_files += 1

    if kept_files == 0 and output_images_dir.exists():
        output_images_dir.rmdir()

    return omitted_files


def clean_doc(source_doc_folder: Path, output_doc_folder: Path, root: Path) -> dict[str, int | str]:
    stats: dict[str, int | str] = {
        "folder": str(source_doc_folder.relative_to(root)),
        "index": 0,
        "store_only": 0,
        "ignore": 0,
        "missing_triage": 0,
        "omitted_files": 0,
    }

    md_path = find_markdown(source_doc_folder)
    if md_path is None:
        stats["error"] = "no markdown file"
        return stats

    text = md_path.read_text(encoding="utf-8")

    def replace(match: re.Match[str]) -> str:
        path = match.group(2)
        basename = path.rsplit("/", 1)[-1]
        stem = Path(basename).stem
        bucket = read_triage(source_doc_folder, stem)

        if bucket is None:
            stats["missing_triage"] += 1
            return match.group(0)
        if bucket == "ignore":
            stats["ignore"] += 1
            return ""
        if bucket in {"store_only", "needs_llm"}:
            stats["store_only"] += 1
            return f"![]({path})"
        if bucket == "index":
            description = read_description(source_doc_folder, stem)
            stats["index"] += 1
            if description:
                safe = description.replace("[", "(").replace("]", ")")
                return f"![{safe}]({path})"
            return f"![]({path})"

        stats["missing_triage"] += 1
        return match.group(0)

    new_text = IMAGE_PATTERN.sub(replace, text)
    new_text = EXCESS_NEWLINES.sub("\n\n", new_text).rstrip() + "\n"

    output_doc_folder.mkdir(parents=True, exist_ok=True)
    (output_doc_folder / md_path.name).write_text(new_text, encoding="utf-8")
    stats["omitted_files"] = copy_kept_images(source_doc_folder, output_doc_folder)
    return stats


def run_clean(root: Path, output_root: Path, emit: LogFn | None = None) -> CleanSummary:
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    if output_root.exists():
        shutil.rmtree(output_root)

    summary = CleanSummary()
    for doc_folder in iter_doc_folders(root):
        output_doc_folder = output_root / doc_folder.relative_to(root)
        stats = clean_doc(doc_folder, output_doc_folder, root)
        summary.folders_processed += 1
        summary.index += int(stats["index"])
        summary.store_only += int(stats["store_only"])
        summary.ignore += int(stats["ignore"])
        summary.missing_triage += int(stats["missing_triage"])
        summary.omitted_files += int(stats["omitted_files"])
        _log(
            emit,
            f"{stats['folder']}: index={stats['index']} store_only={stats['store_only']} "
            f"ignore={stats['ignore']} omitted={stats['omitted_files']}",
        )

    _log(
        emit,
        "Clean summary: "
        f"folders={summary.folders_processed}, index={summary.index}, "
        f"store_only={summary.store_only}, ignore={summary.ignore}",
    )
    return summary
