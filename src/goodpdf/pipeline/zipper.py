from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from goodpdf.pipeline.jobs import LogFn


@dataclass(slots=True)
class ZipSummary:
    archive_path: Path
    file_count: int


def create_zip(source_root: Path, archive_path: Path, emit: LogFn | None = None) -> ZipSummary:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    file_count = 0
    if emit is not None:
        emit(f"Creating zip archive at {archive_path}")
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(source_root.rglob("*")):
            if not path.is_file():
                continue
            archive.write(path, path.relative_to(source_root))
            file_count += 1
    if emit is not None:
        emit(f"Zip complete: {file_count} files")
    return ZipSummary(archive_path=archive_path, file_count=file_count)
