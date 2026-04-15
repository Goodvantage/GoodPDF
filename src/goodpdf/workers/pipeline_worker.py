from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from goodpdf.pipeline.jobs import JobRequest, PipelineStage


class PipelineWorker(QObject):
    log = Signal(str)
    stage_changed = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, request: JobRequest) -> None:
        super().__init__()
        self.request = request

    @Slot()
    def run(self) -> None:
        try:
            from goodpdf.pipeline.runner import run_pipeline

            result = run_pipeline(
                self.request,
                emit=self.log.emit,
                stage_callback=self._emit_stage,
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)

    def _emit_stage(self, stage: PipelineStage) -> None:
        self.stage_changed.emit(stage.value)
