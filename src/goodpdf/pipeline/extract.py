from __future__ import annotations

import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from marker.config.parser import ConfigParser
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered

from goodpdf.pipeline.jobs import LogFn, normalize_language_code

IMAGE_NAME_RE = re.compile(r"^_page_(\d+)_(Figure|Picture)_(\d+)\.[A-Za-z0-9]+$")


@dataclass(slots=True)
class ExtractionSummary:
    converted: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def _log(emit: LogFn | None, message: str) -> None:
    if emit is not None:
        emit(message)


def build_converter() -> PdfConverter:
    config_parser = ConfigParser({"output_format": "markdown"})
    return PdfConverter(
        config=config_parser.generate_config_dict(),
        artifact_dict=create_model_dict(),
        processor_list=config_parser.get_processors(),
        renderer=config_parser.get_renderer(),
        llm_service=config_parser.get_llm_service(),
    )


def parse_image_name(image_name: str) -> dict[str, int | str] | None:
    match = IMAGE_NAME_RE.match(image_name)
    if not match:
        return None

    page, block_type, marker_index = match.groups()
    return {
        "page": int(page),
        "marker_block_type": block_type,
        "marker_index": int(marker_index),
    }


def rewrite_image_links(markdown: str, image_names: list[str]) -> str:
    rewritten = markdown
    for image_name in image_names:
        rewritten = rewritten.replace(f"({image_name})", f"(images/{image_name})")
        rewritten = rewritten.replace(f"src='{image_name}'", f"src='images/{image_name}'")
        rewritten = rewritten.replace(f'src="{image_name}"', f'src="images/{image_name}"')
    return rewritten


def output_paths(pdf_output_dir: Path, doc_id: str) -> tuple[Path, Path, Path]:
    return (
        pdf_output_dir / f"{doc_id}.md",
        pdf_output_dir / f"{doc_id}_meta.json",
        pdf_output_dir / "manifest.json",
    )


def has_complete_output(pdf_output_dir: Path, doc_id: str) -> bool:
    md_path, meta_path, manifest_path = output_paths(pdf_output_dir, doc_id)
    return md_path.exists() and meta_path.exists() and manifest_path.exists()


def relative_to_job_root(job_root: Path, path: Path) -> str:
    return str(path.relative_to(job_root))


def image_manifest_entry(language_code: str, doc_id: str, image_name: str) -> dict[str, object]:
    entry: dict[str, object] = {"filename": image_name, "path": f"images/{image_name}"}
    parsed = parse_image_name(image_name)
    if parsed is None:
        return entry

    entry.update(parsed)
    entry["id"] = (
        f"img:{language_code}:{doc_id}:p{parsed['page']}:{parsed['marker_block_type']}:{parsed['marker_index']}"
    )
    return entry


def simplify_table_of_contents(
    table_of_contents: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "title": item.get("title"),
            "heading_level": item.get("heading_level"),
            "page_id": item.get("page_id"),
        }
        for item in table_of_contents
    ]


def write_document_outputs(
    *,
    language_code: str,
    source_pdf: Path,
    marker_root: Path,
    pdf_output_dir: Path,
    markdown: str,
    images: dict[str, object],
    metadata: dict[str, object],
) -> tuple[int, int]:
    job_root = marker_root.parent
    doc_id = source_pdf.stem
    md_path, meta_path, manifest_path = output_paths(pdf_output_dir, doc_id)
    images_dir = pdf_output_dir / "images"

    pdf_output_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(exist_ok=True)

    image_names = sorted(images)
    for image_name in image_names:
        images[image_name].save(images_dir / image_name)

    markdown = rewrite_image_links(markdown, image_names).rstrip() + "\n"
    md_path.write_text(markdown, encoding="utf-8")
    meta_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    image_entries = [
        image_manifest_entry(language_code, doc_id, image_name) for image_name in image_names
    ]
    manifest = {
        "doc_id": doc_id,
        "lang": language_code,
        "source_pdf": relative_to_job_root(job_root, source_pdf),
        "markdown_path": relative_to_job_root(job_root, md_path),
        "metadata_path": relative_to_job_root(job_root, meta_path),
        "image_dir": relative_to_job_root(job_root, images_dir),
        "markdown_line_count": len(markdown.splitlines()),
        "image_count": len(image_entries),
        "page_count": len(metadata.get("page_stats", [])),
        "table_of_contents": simplify_table_of_contents(metadata.get("table_of_contents", [])),
        "images": image_entries,
        "generated_at": datetime.now(UTC).isoformat(),
        "marker_version": importlib.metadata.version("marker-pdf"),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return len(markdown.splitlines()), len(image_entries)


def convert_single_pdf(
    *,
    language_code: str,
    source_pdf: Path,
    marker_root: Path,
    pdf_output_dir: Path,
) -> tuple[int, int]:
    converter = build_converter()
    rendered = converter(str(source_pdf))
    markdown, _, images = text_from_rendered(rendered)
    metadata = rendered.metadata
    return write_document_outputs(
        language_code=language_code,
        source_pdf=source_pdf,
        marker_root=marker_root,
        pdf_output_dir=pdf_output_dir,
        markdown=markdown,
        images=images,
        metadata=metadata,
    )


def summarize_document_output(pdf_output_dir: Path, doc_id: str) -> tuple[int, int]:
    _, _, manifest_path = output_paths(pdf_output_dir, doc_id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return manifest.get("markdown_line_count", 0), manifest.get("image_count", 0)


def write_index(marker_root: Path, language_code: str) -> None:
    job_root = marker_root.parent
    documents = []
    for manifest_path in sorted(marker_root.glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        documents.append(
            {
                "doc_id": manifest["doc_id"],
                "lang": manifest["lang"],
                "source_pdf": manifest["source_pdf"],
                "markdown_path": manifest["markdown_path"],
                "metadata_path": manifest["metadata_path"],
                "markdown_line_count": manifest.get("markdown_line_count", 0),
                "image_dir": manifest["image_dir"],
                "image_count": manifest["image_count"],
                "manifest_path": relative_to_job_root(job_root, manifest_path),
            }
        )

    index = {
        "language": language_code,
        "document_count": len(documents),
        "generated_at": datetime.now(UTC).isoformat(),
        "documents": documents,
    }
    (marker_root / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run_single_pdf_subprocess(
    language_code: str,
    source_pdf: Path,
    marker_root: Path,
    *,
    torch_device: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    if torch_device is not None:
        env["TORCH_DEVICE"] = torch_device
    if getattr(sys, "frozen", False):
        command = [
            sys.executable,
            "--internal-extract",
            "--internal-language-code",
            language_code,
            "--internal-pdf",
            str(source_pdf),
            "--internal-output-root",
            str(marker_root),
        ]
    else:
        command = [
            sys.executable,
            "-m",
            "goodpdf.main",
            "--internal-extract",
            "--internal-language-code",
            language_code,
            "--internal-pdf",
            str(source_pdf),
            "--internal-output-root",
            str(marker_root),
        ]
    return subprocess.run(
        command,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def run_extraction(
    source_pdfs: list[Path],
    marker_root: Path,
    language_code: str,
    *,
    skip_existing: bool = False,
    no_isolation: bool = False,
    emit: LogFn | None = None,
) -> ExtractionSummary:
    summary = ExtractionSummary()
    marker_root.mkdir(parents=True, exist_ok=True)
    _log(emit, f"Converting {len(source_pdfs)} PDFs into {marker_root}")
    normalized_language_code = normalize_language_code(language_code)

    for index, source_pdf in enumerate(source_pdfs, 1):
        doc_id = source_pdf.stem
        pdf_output_dir = marker_root / doc_id
        if skip_existing and has_complete_output(pdf_output_dir, doc_id):
            summary.skipped += 1
            _log(emit, f"[{index}/{len(source_pdfs)}] SKIP {source_pdf.name}")
            continue

        if pdf_output_dir.exists():
            shutil.rmtree(pdf_output_dir)

        started = time.time()
        _log(emit, f"[{index}/{len(source_pdfs)}] Extracting {source_pdf.name}")
        try:
            if no_isolation:
                used_cpu_fallback = False
                line_count, image_count = convert_single_pdf(
                    language_code=normalized_language_code,
                    source_pdf=source_pdf,
                    marker_root=marker_root,
                    pdf_output_dir=pdf_output_dir,
                )
            else:
                used_cpu_fallback = False
                result = run_single_pdf_subprocess(
                    normalized_language_code,
                    source_pdf,
                    marker_root,
                )
                if result.returncode != 0:
                    stderr = (result.stderr or result.stdout).strip()
                    if stderr:
                        _log(emit, f"  initial failure: {stderr}")
                    _log(emit, "  retrying on CPU...")
                    result = run_single_pdf_subprocess(
                        normalized_language_code,
                        source_pdf,
                        marker_root,
                        torch_device="cpu",
                    )
                    used_cpu_fallback = result.returncode == 0
                if result.returncode != 0:
                    stderr = (result.stderr or result.stdout).strip()
                    detail = stderr or f"subprocess exited with status {result.returncode}"
                    raise RuntimeError(detail)
                if not has_complete_output(pdf_output_dir, doc_id):
                    raise RuntimeError("subprocess finished without writing complete output")
                line_count, image_count = summarize_document_output(pdf_output_dir, doc_id)

            elapsed = time.time() - started
            fallback_note = " with CPU fallback" if used_cpu_fallback else ""
            summary.converted += 1
            _log(
                emit,
                f"  -> OK ({line_count} lines, {image_count} images, {elapsed:.1f}s{fallback_note})",
            )
        except Exception as exc:  # noqa: BLE001
            if pdf_output_dir.exists() and not has_complete_output(pdf_output_dir, doc_id):
                shutil.rmtree(pdf_output_dir)
            elapsed = time.time() - started
            summary.failed += 1
            summary.errors.append(f"{source_pdf.name}: {exc}")
            _log(emit, f"  -> ERROR ({elapsed:.1f}s): {exc}")

    write_index(marker_root, normalized_language_code)
    _log(emit, f"Extraction complete: {summary.converted} converted, {summary.failed} failed")
    return summary


def run_internal_extract(language_code: str, source_pdf: Path, marker_root: Path) -> int:
    language_code = normalize_language_code(language_code)
    pdf_output_dir = marker_root / source_pdf.stem

    if pdf_output_dir.exists():
        shutil.rmtree(pdf_output_dir)

    try:
        line_count, image_count = convert_single_pdf(
            language_code=language_code,
            source_pdf=source_pdf,
            marker_root=marker_root,
            pdf_output_dir=pdf_output_dir,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Internal conversion failed: {source_pdf.name}: {exc}", file=sys.stderr)
        return 1

    print(
        f"Internal conversion complete: {source_pdf.name} ({line_count} lines, {image_count} images)"
    )
    return 0
