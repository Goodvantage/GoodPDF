from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from goodpdf.pipeline.clean import run_clean
from goodpdf.pipeline.describe import run_describe
from goodpdf.pipeline.extract import run_extraction
from goodpdf.pipeline.jobs import (
    JobPaths,
    JobRequest,
    JobResult,
    LogFn,
    PipelineStage,
    StageFn,
    build_job_paths,
)
from goodpdf.pipeline.triage import run_triage
from goodpdf.pipeline.zipper import create_zip
from goodpdf.settings.config import AppConfig


def run_pipeline(
    request: JobRequest,
    *,
    emit: LogFn | None = None,
    stage_callback: StageFn | None = None,
) -> JobResult:
    config = AppConfig.default()
    source_pdfs = request.validated_pdfs()
    paths = build_job_paths(request, config.workspace_dir)
    _prepare_workspace(paths)
    logger = PipelineLogger(paths.log_path, emit)

    def set_stage(stage: PipelineStage) -> None:
        logger.log(f"== {stage.value} ==")
        if stage_callback is not None:
            stage_callback(stage)

    logger.log(f"Starting job {paths.job_id}")
    logger.log(f"Language: {request.normalized_language()}")
    logger.log(f"PDF count: {len(source_pdfs)}")

    copied_pdfs = _copy_source_pdfs(source_pdfs, paths, logger.log)
    _write_request(request, copied_pdfs, paths)

    set_stage(PipelineStage.EXTRACT)
    extraction_summary = run_extraction(
        copied_pdfs,
        paths.marker_dir,
        request.normalized_language(),
        emit=logger.log,
    )

    extracted_docs = sum(
        1 for doc in paths.marker_dir.iterdir() if doc.is_dir() and (doc / "manifest.json").exists()
    )
    if extracted_docs == 0:
        errors = extraction_summary.errors or ["No PDFs were successfully extracted."]
        _write_reports(paths, extraction_summary.errors)
        result = JobResult(
            paths=paths,
            extracted_docs=0,
            failed_docs=extraction_summary.failed,
            cleaned_docs=0,
            archive_path=paths.archive_path,
            had_cloud_descriptions=False,
            errors=errors,
        )
        _write_summary(result, paths)
        raise RuntimeError("No PDFs were successfully extracted.")

    set_stage(PipelineStage.TRIAGE)
    triage_summary = run_triage(paths.marker_dir, emit=logger.log)

    had_cloud_descriptions = False
    if request.use_cloud_descriptions:
        set_stage(PipelineStage.DESCRIBE)
        describe_summary = run_describe(
            paths.marker_dir,
            model=request.llm_model,
            api_key=request.llm_api_key,
            api_base=request.llm_api_base,
            emit=logger.log,
        )
        had_cloud_descriptions = True
    else:
        describe_summary = None
        logger.log("Skipping cloud descriptions; candidate images will remain as store-only.")

    set_stage(PipelineStage.CLEAN)
    clean_summary = run_clean(paths.marker_dir, paths.cleaned_dir, emit=logger.log)

    set_stage(PipelineStage.ZIP)
    zip_summary = create_zip(paths.cleaned_dir, paths.archive_path, emit=logger.log)

    errors = list(extraction_summary.errors)
    _write_reports(paths, errors)
    result = JobResult(
        paths=paths,
        extracted_docs=extracted_docs,
        failed_docs=extraction_summary.failed,
        cleaned_docs=clean_summary.folders_processed,
        archive_path=zip_summary.archive_path,
        had_cloud_descriptions=had_cloud_descriptions,
        errors=errors,
    )
    set_stage(PipelineStage.REPORT)
    _write_summary(
        result,
        paths,
        extraction_summary=asdict(extraction_summary),
        triage_summary=asdict(triage_summary),
        describe_summary=asdict(describe_summary) if describe_summary is not None else None,
        clean_summary=asdict(clean_summary),
        zip_summary=asdict(zip_summary),
    )
    logger.log(f"Job finished. Archive: {paths.archive_path}")
    return result


class PipelineLogger:
    def __init__(self, log_path: Path, emit: LogFn | None = None) -> None:
        self.log_path = log_path
        self.emit = emit

    def log(self, message: str) -> None:
        timestamped = f"[{datetime.now(UTC).strftime('%H:%M:%S')}] {message}"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(timestamped + "\n")
        if self.emit is not None:
            self.emit(timestamped)


def _prepare_workspace(paths: JobPaths) -> None:
    paths.source_dir.mkdir(parents=True, exist_ok=True)
    paths.marker_dir.mkdir(parents=True, exist_ok=True)
    paths.cleaned_dir.mkdir(parents=True, exist_ok=True)
    paths.archive_dir.mkdir(parents=True, exist_ok=True)
    paths.reports_dir.mkdir(parents=True, exist_ok=True)


def _copy_source_pdfs(source_pdfs: list[Path], paths: JobPaths, emit: LogFn | None) -> list[Path]:
    copied = []
    for source_pdf in source_pdfs:
        destination = paths.source_dir / source_pdf.name
        shutil.copy2(source_pdf, destination)
        copied.append(destination)
        if emit is not None:
            emit(f"Copied source PDF: {source_pdf.name}")
    return copied


def _write_request(request: JobRequest, source_pdfs: list[Path], paths: JobPaths) -> None:
    payload = {
        "language": request.normalized_language(),
        "use_cloud_descriptions": request.use_cloud_descriptions,
        "llm_model": request.llm_model,
        "llm_api_base": request.llm_api_base,
        "has_llm_api_key": bool(request.llm_api_key),
        "created_at": datetime.now(UTC).isoformat(),
        "source_pdfs": [str(path) for path in source_pdfs],
    }
    paths.request_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_reports(paths: JobPaths, errors: list[str]) -> None:
    if errors:
        paths.error_report_path.write_text("\n".join(errors) + "\n", encoding="utf-8")


def _write_summary(
    result: JobResult,
    paths: JobPaths,
    **extra: object,
) -> None:
    payload = {
        "job_id": result.paths.job_id,
        "extracted_docs": result.extracted_docs,
        "failed_docs": result.failed_docs,
        "cleaned_docs": result.cleaned_docs,
        "archive_path": str(result.archive_path),
        "had_cloud_descriptions": result.had_cloud_descriptions,
        "errors": result.errors,
        **extra,
    }
    paths.summary_path.write_text(
        json.dumps(payload, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
