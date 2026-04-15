from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from goodpdf.pipeline.jobs import (
    JobPaths,
    JobRequest,
    JobResult,
    LogFn,
    PipelineStage,
    StageFn,
    build_job_paths,
)
from goodpdf.settings.config import AppConfig


def run_pipeline(
    request: JobRequest,
    *,
    emit: LogFn | None = None,
    stage_callback: StageFn | None = None,
) -> JobResult:
    config = AppConfig.default()
    request.validate()
    paths = build_job_paths(request, config.workspace_dir)
    _prepare_workspace(paths)
    logger = PipelineLogger(paths.log_path, emit)

    def set_stage(stage: PipelineStage) -> None:
        logger.log(f"== {stage.value} ==")
        if stage_callback is not None:
            stage_callback(stage)

    logger.log(f"Starting job {paths.job_id}")
    logger.log(f"Language: {request.normalized_language()}")

    extraction_summary = None
    source_pdfs: list[Path] = []
    if request.is_resume():
        logger.log(f"Start stage: {request.start_stage.value}")
        logger.log(f"Using existing marker folder: {paths.marker_dir}")
        extracted_docs = _validate_resume_marker_root(paths.marker_dir, request.start_stage)
        logger.log(f"Marker docs detected: {extracted_docs}")
        _write_request(request, source_pdfs, paths)
    else:
        source_pdfs = request.validated_pdfs()
        logger.log(f"PDF count: {len(source_pdfs)}")

        copied_pdfs = _copy_source_pdfs(source_pdfs, paths, logger.log)
        _write_request(request, copied_pdfs, paths)

        set_stage(PipelineStage.EXTRACT)
        from goodpdf.pipeline.extract import run_extraction

        extraction_summary = run_extraction(
            copied_pdfs,
            paths.marker_dir,
            request.normalized_language(),
            emit=logger.log,
        )

        extracted_docs = _count_extracted_docs(paths.marker_dir)
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

    triage_summary = None
    if _should_run_stage(request.start_stage, PipelineStage.TRIAGE):
        set_stage(PipelineStage.TRIAGE)
        from goodpdf.pipeline.triage import run_triage

        triage_summary = run_triage(paths.marker_dir, emit=logger.log)

    had_cloud_descriptions = False
    describe_summary = None
    if request.use_cloud_descriptions and _should_run_stage(
        request.start_stage, PipelineStage.DESCRIBE
    ):
        set_stage(PipelineStage.DESCRIBE)
        from goodpdf.pipeline.describe import run_describe

        describe_summary = run_describe(
            paths.marker_dir,
            model=request.llm_model,
            api_key=request.llm_api_key,
            api_base=request.llm_api_base,
            extra_caption_labels=request.additional_caption_labels,
            emit=logger.log,
        )
        had_cloud_descriptions = True
    elif _should_run_stage(request.start_stage, PipelineStage.DESCRIBE):
        logger.log("Skipping cloud descriptions; candidate images will remain as store-only.")

    set_stage(PipelineStage.CLEAN)
    from goodpdf.pipeline.clean import run_clean

    clean_summary = run_clean(paths.marker_dir, paths.cleaned_dir, emit=logger.log)

    set_stage(PipelineStage.ZIP)
    from goodpdf.pipeline.zipper import create_zip

    zip_summary = create_zip(paths.cleaned_dir, paths.archive_path, emit=logger.log)

    errors = list(extraction_summary.errors) if extraction_summary is not None else []
    _write_reports(paths, errors)
    result = JobResult(
        paths=paths,
        extracted_docs=extracted_docs,
        failed_docs=extraction_summary.failed if extraction_summary is not None else 0,
        cleaned_docs=clean_summary.folders_processed,
        archive_path=zip_summary.archive_path,
        had_cloud_descriptions=had_cloud_descriptions,
        errors=errors,
    )
    set_stage(PipelineStage.REPORT)
    _write_summary(
        result,
        paths,
        extraction_summary=asdict(extraction_summary) if extraction_summary is not None else None,
        triage_summary=asdict(triage_summary) if triage_summary is not None else None,
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
    if not paths.marker_dir.exists():
        paths.marker_dir.mkdir(parents=True, exist_ok=True)
    paths.cleaned_dir.mkdir(parents=True, exist_ok=True)
    paths.archive_dir.mkdir(parents=True, exist_ok=True)
    paths.reports_dir.mkdir(parents=True, exist_ok=True)


def _count_extracted_docs(marker_dir: Path) -> int:
    count = 0
    for doc in marker_dir.iterdir():
        if not doc.is_dir():
            continue
        if (doc / "manifest.json").exists():
            count += 1
            continue
        for candidate in doc.iterdir():
            if candidate.is_file() and candidate.suffix.lower() in {".md", ".markdown"}:
                count += 1
                break
    return count


def _has_sidecar(marker_dir: Path, suffix: str) -> bool:
    return any(marker_dir.rglob(f"*{suffix}"))


def _validate_resume_marker_root(marker_dir: Path, start_stage: PipelineStage) -> int:
    extracted_docs = _count_extracted_docs(marker_dir)
    if extracted_docs == 0:
        raise RuntimeError("No extracted documents were found in the selected marker folder.")
    if start_stage in {PipelineStage.DESCRIBE, PipelineStage.CLEAN} and not _has_sidecar(
        marker_dir, ".triage"
    ):
        raise RuntimeError(
            "No triage sidecars were found in the selected marker folder. Start from Triage or choose a folder that already ran Triage."
        )
    return extracted_docs


def _should_run_stage(start_stage: PipelineStage, stage: PipelineStage) -> bool:
    ordered = [
        PipelineStage.EXTRACT,
        PipelineStage.TRIAGE,
        PipelineStage.DESCRIBE,
        PipelineStage.CLEAN,
        PipelineStage.ZIP,
    ]
    return ordered.index(stage) >= ordered.index(start_stage)


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
        "start_stage": request.start_stage.value,
        "existing_marker_root": str(request.resolved_existing_marker_root())
        if request.resolved_existing_marker_root() is not None
        else None,
        "use_cloud_descriptions": request.use_cloud_descriptions,
        "additional_caption_labels": request.additional_caption_labels,
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
