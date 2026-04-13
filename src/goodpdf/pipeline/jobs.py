from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Callable

import pycountry

LEGACY_LANGUAGE_ALIASES = {
    "english": "en",
    "bahasa": "id",
    "bahasa indonesia": "id",
    "indonesian": "id",
    "malay": "ms",
    "spanish": "es",
    "portuguese": "pt",
    "french": "fr",
    "vietnamese": "vi",
    "thai": "th",
}

ISO_LANGUAGE_CODES = tuple(
    sorted(
        {
            language.alpha_2.lower()
            for language in pycountry.languages
            if hasattr(language, "alpha_2")
        }
    )
)
ISO_LANGUAGE_CODE_SET = set(ISO_LANGUAGE_CODES)


class PipelineStage(StrEnum):
    PREPARE = "Prepare workspace"
    EXTRACT = "Extract markdown and images"
    TRIAGE = "Triage extracted images"
    DESCRIBE = "Describe retrieval-useful images"
    CLEAN = "Build cleaned import corpus"
    ZIP = "Create Frappe import zip"
    REPORT = "Write logs and reports"


PIPELINE_STAGES = [stage.value for stage in PipelineStage]
LogFn = Callable[[str], None]
StageFn = Callable[[PipelineStage], None]


def normalize_language_code(value: str) -> str:
    normalized = value.strip().lower()
    normalized = LEGACY_LANGUAGE_ALIASES.get(normalized, normalized)
    if normalized not in ISO_LANGUAGE_CODE_SET:
        raise ValueError(f"Unsupported ISO 639-1 language code: {value}")
    return normalized


def language_options() -> list[tuple[str, str]]:
    options = []
    for code in ISO_LANGUAGE_CODES:
        language = pycountry.languages.get(alpha_2=code)
        name = getattr(language, "name", code.upper()) if language is not None else code.upper()
        options.append((f"{code} - {name}", code))
    return options


@dataclass(slots=True)
class JobRequest:
    source_pdfs: list[Path] = field(default_factory=list)
    language: str = "en"
    use_cloud_descriptions: bool = True
    output_root: Path | None = None
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str | None = None
    llm_api_base: str | None = None

    def normalized_language(self) -> str:
        return normalize_language_code(self.language)

    def validated_pdfs(self) -> list[Path]:
        pdfs = [path.expanduser().resolve() for path in self.source_pdfs]
        if not pdfs:
            raise ValueError("No PDFs selected.")

        missing = [path for path in pdfs if not path.is_file()]
        if missing:
            missing_text = ", ".join(path.name for path in missing)
            raise ValueError(f"Missing PDF files: {missing_text}")

        duplicate_stems = sorted(
            {path.stem for path in pdfs if sum(p.stem == path.stem for p in pdfs) > 1}
        )
        if duplicate_stems:
            duplicate_text = ", ".join(duplicate_stems)
            raise ValueError(
                f"Selected PDFs must have unique filenames. Duplicate stems: {duplicate_text}"
            )

        return pdfs


@dataclass(slots=True)
class JobPaths:
    job_id: str
    workspace_root: Path
    job_root: Path
    source_dir: Path
    marker_dir: Path
    cleaned_dir: Path
    archive_dir: Path
    reports_dir: Path
    archive_path: Path
    request_path: Path
    summary_path: Path
    log_path: Path
    error_report_path: Path


@dataclass(slots=True)
class JobResult:
    paths: JobPaths
    extracted_docs: int
    failed_docs: int
    cleaned_docs: int
    archive_path: Path
    had_cloud_descriptions: bool
    errors: list[str] = field(default_factory=list)


def build_job_paths(request: JobRequest, default_workspace: Path) -> JobPaths:
    workspace_root = (request.output_root or default_workspace).expanduser().resolve()
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    language_code = request.normalized_language()
    job_id = f"{timestamp}_{language_code}_{len(request.source_pdfs)}pdfs"
    job_root = workspace_root / "jobs" / job_id
    source_dir = job_root / "source"
    marker_dir = job_root / "marker"
    cleaned_dir = job_root / "cleaned"
    archive_dir = job_root / "archive"
    reports_dir = job_root / "reports"
    archive_path = archive_dir / f"goodpdf_{language_code}.zip"
    return JobPaths(
        job_id=job_id,
        workspace_root=workspace_root,
        job_root=job_root,
        source_dir=source_dir,
        marker_dir=marker_dir,
        cleaned_dir=cleaned_dir,
        archive_dir=archive_dir,
        reports_dir=reports_dir,
        archive_path=archive_path,
        request_path=reports_dir / "job_request.json",
        summary_path=reports_dir / "summary.json",
        log_path=reports_dir / "pipeline.log",
        error_report_path=reports_dir / "errors.txt",
    )
