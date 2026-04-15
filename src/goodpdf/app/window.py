from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from goodpdf.pipeline.captions import DEFAULT_CAPTION_LABELS, parse_caption_labels_text
from goodpdf.pipeline.jobs import (
    PIPELINE_STAGES,
    RESUME_START_STAGES,
    JobRequest,
    JobResult,
    PipelineStage,
    language_options,
)
from goodpdf.settings import clear_api_key, load_api_key, save_api_key
from goodpdf.settings.config import AppConfig
from goodpdf.workers.pipeline_worker import PipelineWorker


class PdfDropListWidget(QListWidget):
    filesDropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self._set_drag_active(False)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._extract_pdf_paths(event.mimeData()):
            event.acceptProposedAction()
            self._set_drag_active(True)
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._extract_pdf_paths(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = self._extract_pdf_paths(event.mimeData())
        self._set_drag_active(False)
        if not paths:
            super().dropEvent(event)
            return
        event.acceptProposedAction()
        self.filesDropped.emit(paths)

    def _extract_pdf_paths(self, mime_data) -> list[Path]:
        if not mime_data.hasUrls():
            return []
        paths: list[Path] = []
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() == ".pdf":
                paths.append(path)
        return paths

    def _set_drag_active(self, active: bool) -> None:
        border_color = "#175cd3" if active else "#98a2b3"
        background = "#eef4ff" if active else "#ffffff"
        self.setStyleSheet(
            "QListWidget {"
            f"border: 2px dashed {border_color};"
            "border-radius: 10px;"
            f"background: {background};"
            "padding: 8px;"
            "}"
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = AppConfig.default()
        self.settings = QSettings(
            self.config.settings_organization,
            self.config.settings_application,
        )
        self._loading_settings = False
        self.selected_pdfs: list[Path] = []
        self.worker_thread: QThread | None = None
        self.worker: PipelineWorker | None = None
        self.last_archive_path: Path | None = None
        self.current_stage_name: str | None = None
        self.setWindowTitle("GoodPDF")
        self.resize(1080, 780)
        self.setCentralWidget(self._build_ui())
        self._load_settings()
        self._update_settings_summary()
        self._set_controls_enabled(True)

    def _build_ui(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("GoodPDF")
        title.setStyleSheet("font-size: 28px; font-weight: 700;")

        subtitle = QLabel(
            "Local PDF-to-RAG desktop app for macOS and Windows. "
            "Select PDFs, run the pipeline, and export a Frappe-ready zip."
        )
        subtitle.setWordWrap(True)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_run_tab(), "Run")
        self.tabs.addTab(self._build_settings_tab(), "Settings")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.tabs)
        return root

    def _build_run_tab(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        job_group = QGroupBox("Job")
        job_layout = QVBoxLayout(job_group)
        job_layout.setSpacing(10)

        language_label = QLabel("Language (ISO 639-1)")
        language_label.setStyleSheet("font-weight: 600;")
        self.language_combo = QComboBox()
        for label, value in language_options():
            self.language_combo.addItem(label, value)
        default_index = self.language_combo.findData("en")
        if default_index >= 0:
            self.language_combo.setCurrentIndex(default_index)
        self.language_combo.currentIndexChanged.connect(self._save_settings)

        start_mode_label = QLabel("Start from")
        start_mode_label.setStyleSheet("font-weight: 600;")
        self.start_mode_combo = QComboBox()
        self.start_mode_combo.addItem("PDFs (full pipeline)", "pdfs")
        self.start_mode_combo.addItem("Existing marker folder", "existing")
        self.start_mode_combo.currentIndexChanged.connect(self._handle_start_mode_change)
        self.start_mode_combo.currentIndexChanged.connect(self._save_settings)

        self.describe_checkbox = QCheckBox("Enable cloud image descriptions")
        self.describe_checkbox.setChecked(True)
        self.describe_checkbox.toggled.connect(self._handle_cloud_toggle)
        self.describe_checkbox.toggled.connect(self._save_settings)

        self.settings_summary_label = QLabel()
        self.settings_summary_label.setWordWrap(True)
        self.settings_summary_label.setStyleSheet("color: #666;")

        job_layout.addWidget(start_mode_label)
        job_layout.addWidget(self.start_mode_combo)
        job_layout.addWidget(language_label)
        job_layout.addWidget(self.language_combo)
        job_layout.addWidget(self.describe_checkbox)
        job_layout.addWidget(self.settings_summary_label)

        self.pdf_group = QGroupBox("PDFs")
        pdf_layout = QVBoxLayout(self.pdf_group)
        pdf_layout.setSpacing(12)

        pdf_controls = QHBoxLayout()
        pdf_controls.setSpacing(12)
        self.add_pdfs_button = QPushButton("Add PDFs")
        self.add_pdfs_button.clicked.connect(self._select_pdfs)
        self.remove_selected_button = QPushButton("Remove Selected")
        self.remove_selected_button.clicked.connect(self._remove_selected)
        self.clear_all_button = QPushButton("Clear")
        self.clear_all_button.clicked.connect(self._clear_pdfs)

        pdf_controls.addWidget(self.add_pdfs_button)
        pdf_controls.addWidget(self.remove_selected_button)
        pdf_controls.addWidget(self.clear_all_button)
        pdf_controls.addStretch(1)

        self.pdfs_label = QLabel("Selected PDFs: 0")
        self.pdf_drop_hint_label = QLabel("Drop PDFs here or use Add PDFs.")
        self.pdf_drop_hint_label.setStyleSheet("color: #666;")

        self.pdfs = PdfDropListWidget()
        self.pdfs.filesDropped.connect(self._add_pdf_paths)

        pdf_layout.addLayout(pdf_controls)
        pdf_layout.addWidget(self.pdfs_label)
        pdf_layout.addWidget(self.pdf_drop_hint_label)
        pdf_layout.addWidget(self.pdfs, stretch=1)

        self.resume_group = QGroupBox("Existing Extraction")
        resume_layout = QVBoxLayout(self.resume_group)
        resume_layout.setSpacing(12)

        resume_path_label = QLabel("Marker folder")
        resume_path_label.setStyleSheet("font-weight: 600;")
        resume_path_row = QHBoxLayout()
        resume_path_row.setSpacing(12)
        self.existing_marker_root_input = QLineEdit()
        self.existing_marker_root_input.setPlaceholderText("Choose an extracted marker folder")
        self.existing_marker_root_input.textChanged.connect(self._save_settings)
        self.choose_existing_marker_root_button = QPushButton("Choose Folder")
        self.choose_existing_marker_root_button.clicked.connect(self._choose_existing_marker_root)
        resume_path_row.addWidget(self.existing_marker_root_input)
        resume_path_row.addWidget(self.choose_existing_marker_root_button)

        resume_stage_label = QLabel("Start stage")
        resume_stage_label.setStyleSheet("font-weight: 600;")
        self.resume_stage_combo = QComboBox()
        for stage in RESUME_START_STAGES:
            self.resume_stage_combo.addItem(stage.value, stage.name)
        self.resume_stage_combo.currentIndexChanged.connect(self._save_settings)

        resume_hint = QLabel(
            "Use an existing marker output folder and continue from Triage, Describe, or Clean. "
            "GoodPDF will create a new cleaned zip job in the workspace and update sidecars in the selected marker folder."
        )
        resume_hint.setWordWrap(True)
        resume_hint.setStyleSheet("color: #666;")

        resume_layout.addWidget(resume_path_label)
        resume_layout.addLayout(resume_path_row)
        resume_layout.addWidget(resume_stage_label)
        resume_layout.addWidget(self.resume_stage_combo)
        resume_layout.addWidget(resume_hint)

        progress_group = QGroupBox("Pipeline Progress")
        progress_layout = QVBoxLayout(progress_group)
        progress_layout.setSpacing(10)

        self.stages_widget = QWidget()
        self.stages_layout = QVBoxLayout(self.stages_widget)
        self.stages_layout.setContentsMargins(0, 0, 0, 0)
        self.stages_layout.setSpacing(8)
        self.stage_labels: list[QLabel] = []
        self._render_stage_list()

        self.stage_label = QLabel("Status: idle")
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)

        progress_layout.addWidget(self.stages_widget)
        progress_layout.addWidget(self.stage_label)
        progress_layout.addWidget(self.log_output, stretch=1)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.run_button = QPushButton("Run Pipeline")
        self.run_button.clicked.connect(self._run_pipeline)
        self.open_output_button = QPushButton("Open Output Folder")
        self.open_output_button.clicked.connect(self._open_output_folder)
        self.open_output_button.setEnabled(False)

        actions.addWidget(self.run_button)
        actions.addWidget(self.open_output_button)
        actions.addStretch(1)

        layout.addWidget(job_group)
        layout.addWidget(self.pdf_group, stretch=1)
        layout.addWidget(self.resume_group, stretch=1)
        layout.addWidget(progress_group, stretch=1)
        layout.addLayout(actions)
        self._update_start_mode_ui()
        return root

    def _build_settings_tab(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        workspace_group = QGroupBox("Workspace")
        workspace_layout = QVBoxLayout(workspace_group)
        workspace_layout.setSpacing(10)

        workspace_label = QLabel("Current folder")
        workspace_label.setStyleSheet("font-weight: 600;")

        self.workspace_value_label = QLabel(str(self.config.workspace_dir))
        self.workspace_value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.workspace_value_label.setWordWrap(True)

        workspace_hint = QLabel(
            "Each job creates its own subfolder under this workspace with source, marker, cleaned, archive, and reports outputs."
        )
        workspace_hint.setWordWrap(True)
        workspace_hint.setStyleSheet("color: #666;")

        workspace_actions = QHBoxLayout()
        workspace_actions.setSpacing(12)
        self.choose_workspace_button = QPushButton("Choose Workspace")
        self.choose_workspace_button.clicked.connect(self._choose_workspace)
        workspace_actions.addWidget(self.choose_workspace_button)
        workspace_actions.addStretch(1)

        workspace_layout.addWidget(workspace_label)
        workspace_layout.addWidget(self.workspace_value_label)
        workspace_layout.addWidget(workspace_hint)
        workspace_layout.addLayout(workspace_actions)

        cloud_group = QGroupBox("Cloud Provider")
        cloud_layout = QVBoxLayout(cloud_group)
        cloud_layout.setSpacing(12)

        api_base_label = QLabel("Base URL")
        api_base_label.setStyleSheet("font-weight: 600;")
        self.llm_api_base_input = QLineEdit(self.config.default_llm_api_base)
        self.llm_api_base_input.setPlaceholderText("https://api.openai.com/v1")
        self.llm_api_base_input.textChanged.connect(self._save_settings)

        model_label = QLabel("Model")
        model_label.setStyleSheet("font-weight: 600;")
        self.llm_model_input = QLineEdit(self.config.default_llm_model)
        self.llm_model_input.setPlaceholderText("gpt-4o-mini")
        self.llm_model_input.textChanged.connect(self._save_settings)

        key_label = QLabel("API key")
        key_label.setStyleSheet("font-weight: 600;")
        self.llm_api_key_input = QLineEdit()
        self.llm_api_key_input.setEchoMode(QLineEdit.Password)
        self.llm_api_key_input.setPlaceholderText("API key")
        self.llm_api_key_input.textChanged.connect(self._update_settings_summary)
        self.llm_api_key_input.editingFinished.connect(self._persist_api_key_if_needed)

        self.remember_api_key_checkbox = QCheckBox("Remember API key securely on this device")
        self.remember_api_key_checkbox.toggled.connect(self._handle_remember_api_key_toggle)
        self.remember_api_key_checkbox.toggled.connect(self._save_settings)

        cloud_hint = QLabel(
            "Use any OpenAI-compatible provider by setting a base URL and model. "
            "If enabled, the API key is stored in the system keychain/keyring."
        )
        cloud_hint.setWordWrap(True)
        cloud_hint.setStyleSheet("color: #666;")

        labels_label = QLabel("Additional caption labels")
        labels_label.setStyleSheet("font-weight: 600;")
        self.additional_caption_labels_input = QPlainTextEdit()
        self.additional_caption_labels_input.setPlaceholderText(
            "One label per line, e.g. skema\ngrafik"
        )
        self.additional_caption_labels_input.setMaximumHeight(120)
        self.additional_caption_labels_input.textChanged.connect(self._save_settings)

        labels_hint = QLabel(
            "Extend caption detection for new languages without changing the regex. "
            f"Built-in labels: {', '.join(DEFAULT_CAPTION_LABELS)}."
        )
        labels_hint.setWordWrap(True)
        labels_hint.setStyleSheet("color: #666;")

        cloud_layout.addWidget(api_base_label)
        cloud_layout.addWidget(self.llm_api_base_input)
        cloud_layout.addWidget(model_label)
        cloud_layout.addWidget(self.llm_model_input)
        cloud_layout.addWidget(key_label)
        cloud_layout.addWidget(self.llm_api_key_input)
        cloud_layout.addWidget(self.remember_api_key_checkbox)
        cloud_layout.addWidget(cloud_hint)
        cloud_layout.addWidget(labels_label)
        cloud_layout.addWidget(self.additional_caption_labels_input)
        cloud_layout.addWidget(labels_hint)

        layout.addWidget(workspace_group)
        layout.addWidget(cloud_group)
        layout.addStretch(1)
        return root

    def _choose_workspace(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose workspace",
            str(self.config.workspace_dir),
        )
        if not selected:
            return
        self.config.workspace_dir = Path(selected)
        self.workspace_value_label.setText(str(self.config.workspace_dir))
        self._save_settings()

    def _choose_existing_marker_root(self) -> None:
        current = self.existing_marker_root_input.text().strip() or str(self.config.workspace_dir)
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose marker folder",
            current,
        )
        if not selected:
            return
        self.existing_marker_root_input.setText(selected)

    def _current_start_mode(self) -> str:
        return self.start_mode_combo.currentData() or "pdfs"

    def _selected_resume_stage(self) -> PipelineStage:
        stage_name = self.resume_stage_combo.currentData() or PipelineStage.TRIAGE.name
        return PipelineStage[stage_name]

    def _additional_caption_labels(self) -> list[str]:
        return list(parse_caption_labels_text(self.additional_caption_labels_input.toPlainText()))

    def _handle_start_mode_change(self, _index: int) -> None:
        self._update_start_mode_ui()
        self._update_settings_summary()

    def _update_start_mode_ui(self) -> None:
        existing_mode = self._current_start_mode() == "existing"
        self.pdf_group.setVisible(not existing_mode)
        self.resume_group.setVisible(existing_mode)
        self.resume_stage_combo.setEnabled(existing_mode and self.run_button.isEnabled())
        self.existing_marker_root_input.setEnabled(existing_mode and self.run_button.isEnabled())
        self.choose_existing_marker_root_button.setEnabled(
            existing_mode and self.run_button.isEnabled()
        )

    def _select_pdfs(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select PDFs",
            str(Path.home()),
            "PDF Files (*.pdf)",
        )
        if not files:
            return
        self._add_pdf_paths([Path(file_path) for file_path in files])

    def _add_pdf_paths(self, paths: list[Path]) -> None:
        added = 0
        for path in paths:
            resolved = path.expanduser().resolve()
            if resolved.suffix.lower() != ".pdf" or not resolved.is_file():
                continue
            if resolved in self.selected_pdfs:
                continue
            self.selected_pdfs.append(resolved)
            item = QListWidgetItem(str(resolved))
            item.setData(Qt.UserRole, resolved)
            self.pdfs.addItem(item)
            added += 1
        if added:
            self._update_pdf_label()

    def _remove_selected(self) -> None:
        selected_items = self.pdfs.selectedItems()
        if not selected_items:
            return
        selected_paths = {item.data(Qt.UserRole) for item in selected_items}
        self.selected_pdfs = [path for path in self.selected_pdfs if path not in selected_paths]
        for item in selected_items:
            self.pdfs.takeItem(self.pdfs.row(item))
        self._update_pdf_label()

    def _clear_pdfs(self) -> None:
        self.selected_pdfs.clear()
        self.pdfs.clear()
        self._update_pdf_label()

    def _run_pipeline(self) -> None:
        if not self._persist_api_key_if_needed(show_warning=True):
            self.tabs.setCurrentIndex(1)
            return

        start_mode = self._current_start_mode()
        existing_marker_root = (
            Path(self.existing_marker_root_input.text().strip())
            if start_mode == "existing" and self.existing_marker_root_input.text().strip()
            else None
        )
        start_stage = (
            self._selected_resume_stage() if start_mode == "existing" else PipelineStage.EXTRACT
        )

        request = JobRequest(
            source_pdfs=self.selected_pdfs if start_mode == "pdfs" else [],
            language=self.language_combo.currentData(),
            use_cloud_descriptions=self.describe_checkbox.isChecked(),
            output_root=self.config.workspace_dir,
            existing_marker_root=existing_marker_root,
            start_stage=start_stage,
            additional_caption_labels=self._additional_caption_labels(),
            llm_model=self.llm_model_input.text().strip() or self.config.default_llm_model,
            llm_api_key=self.llm_api_key_input.text().strip() or None,
            llm_api_base=self.llm_api_base_input.text().strip() or None,
        )
        try:
            request.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid pipeline settings", str(exc))
            return

        self.log_output.clear()
        self.stage_label.setText("Status: starting")
        self.current_stage_name = None
        self._render_stage_list()
        self.last_archive_path = None
        self.open_output_button.setEnabled(False)
        self._set_controls_enabled(False)
        self.tabs.setCurrentIndex(0)

        self.worker_thread = QThread(self)
        self.worker = PipelineWorker(request)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.log.connect(self.log_output.appendPlainText)
        self.worker.stage_changed.connect(self._set_stage)
        self.worker.finished.connect(self._job_finished)
        self.worker.failed.connect(self._job_failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.start()

    def _set_stage(self, stage: str) -> None:
        self.current_stage_name = stage
        self.stage_label.setText(f"Status: {stage}")
        self._render_stage_list(stage)

    def _job_finished(self, result: object) -> None:
        self._cleanup_worker()
        job_result = result if isinstance(result, JobResult) else None
        if job_result is None:
            self.stage_label.setText("Status: finished")
            self._set_controls_enabled(True)
            return

        self.last_archive_path = job_result.archive_path
        self.current_stage_name = PIPELINE_STAGES[-1]
        self.stage_label.setText("Status: finished")
        self._render_stage_list(PIPELINE_STAGES[-1])
        self.open_output_button.setEnabled(True)
        self._set_controls_enabled(True)

        details = [f"Archive created at:\n{job_result.archive_path}"]
        if job_result.failed_docs:
            details.append(
                f"\n{job_result.failed_docs} PDFs failed and were listed in the reports."
            )

        QMessageBox.information(self, "Pipeline complete", "".join(details))

    def _job_failed(self, error: str) -> None:
        self._cleanup_worker()
        self.stage_label.setText("Status: failed")
        self._render_stage_list(failed_stage=self.current_stage_name)
        self._set_controls_enabled(True)
        QMessageBox.critical(self, "Pipeline failed", error)

    def _cleanup_worker(self) -> None:
        self.worker = None
        self.worker_thread = None

    def _open_output_folder(self) -> None:
        if self.last_archive_path is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_archive_path.parent)))

    def _set_controls_enabled(self, enabled: bool) -> None:
        cloud_enabled = enabled and self.describe_checkbox.isChecked()
        existing_mode = self._current_start_mode() == "existing"
        self.language_combo.setEnabled(enabled)
        self.start_mode_combo.setEnabled(enabled)
        self.describe_checkbox.setEnabled(enabled)
        self.llm_api_base_input.setEnabled(cloud_enabled)
        self.llm_model_input.setEnabled(cloud_enabled)
        self.llm_api_key_input.setEnabled(cloud_enabled)
        self.remember_api_key_checkbox.setEnabled(cloud_enabled)
        self.additional_caption_labels_input.setEnabled(enabled)
        self.choose_workspace_button.setEnabled(enabled)
        self.add_pdfs_button.setEnabled(enabled and not existing_mode)
        self.remove_selected_button.setEnabled(enabled and not existing_mode)
        self.clear_all_button.setEnabled(enabled and not existing_mode)
        self.existing_marker_root_input.setEnabled(enabled and existing_mode)
        self.choose_existing_marker_root_button.setEnabled(enabled and existing_mode)
        self.resume_stage_combo.setEnabled(enabled and existing_mode)
        self.run_button.setEnabled(enabled)
        self._update_start_mode_ui()

    def _update_pdf_label(self) -> None:
        self.pdfs_label.setText(f"Selected PDFs: {len(self.selected_pdfs)}")

    def _render_stage_list(
        self,
        active_stage: str | None = None,
        *,
        failed_stage: str | None = None,
    ) -> None:
        active_index = (
            PIPELINE_STAGES.index(active_stage) if active_stage in PIPELINE_STAGES else None
        )
        failed_index = (
            PIPELINE_STAGES.index(failed_stage) if failed_stage in PIPELINE_STAGES else None
        )

        while self.stages_layout.count():
            item = self.stages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.stage_labels.clear()

        for index, stage in enumerate(PIPELINE_STAGES):
            if failed_index is not None and index == failed_index:
                prefix = "✕"
                color = "#b42318"
                weight = "700"
            elif active_index is None:
                prefix = "○"
                color = "#344054"
                weight = "500"
            elif index < active_index:
                prefix = "✓"
                color = "#027a48"
                weight = "600"
            elif index == active_index:
                prefix = "◉"
                color = "#175cd3"
                weight = "700"
            else:
                prefix = "○"
                color = "#344054"
                weight = "500"

            label = QLabel(f"{prefix}  {stage}")
            label.setStyleSheet(f"font-size: 14px; color: {color}; font-weight: {weight};")
            self.stage_labels.append(label)
            self.stages_layout.addWidget(label)
        self.stages_layout.addStretch(1)

    def _handle_cloud_toggle(self, _checked: bool) -> None:
        self._set_controls_enabled(self.run_button.isEnabled())
        self._update_settings_summary()

    def _handle_remember_api_key_toggle(self, checked: bool) -> None:
        if self._loading_settings:
            return
        if checked:
            self._persist_api_key_if_needed(show_warning=True)
        else:
            clear_api_key(self.config)
        self._update_settings_summary()

    def _persist_api_key_if_needed(self, show_warning: bool = False) -> bool:
        if not self.remember_api_key_checkbox.isChecked():
            return True
        api_key = self.llm_api_key_input.text().strip()
        if not api_key:
            success = clear_api_key(self.config)
            if not success and show_warning:
                QMessageBox.warning(self, "Keychain error", "Could not clear the saved API key.")
            return success
        success = save_api_key(self.config, api_key)
        if not success and show_warning:
            QMessageBox.warning(
                self,
                "Keychain error",
                "Could not save the API key to the system keychain/keyring.",
            )
        return success

    def _update_settings_summary(self) -> None:
        cloud_mode = (
            "Cloud descriptions on"
            if self.describe_checkbox.isChecked()
            else "Cloud descriptions off"
        )
        start_mode = (
            "Existing marker folder"
            if self._current_start_mode() == "existing"
            else "Selected PDFs"
        )
        provider_bits = []
        api_base = self.llm_api_base_input.text().strip()
        model = self.llm_model_input.text().strip()
        if api_base:
            provider_bits.append(api_base)
        if model:
            provider_bits.append(model)
        if self.llm_api_key_input.text().strip():
            provider_bits.append(
                "API key saved in keychain"
                if self.remember_api_key_checkbox.isChecked()
                else "session API key set"
            )
        provider_text = " | ".join(provider_bits) if provider_bits else "No provider configured"
        extra_label_count = len(self._additional_caption_labels())
        details = [
            f"Workspace: {self.config.workspace_dir}",
            f"{start_mode} | {cloud_mode} | {provider_text}",
        ]
        if (
            self._current_start_mode() == "existing"
            and self.existing_marker_root_input.text().strip()
        ):
            details.append(f"Marker folder: {self.existing_marker_root_input.text().strip()}")
        if extra_label_count:
            details.append(f"Extra caption labels: {extra_label_count}")
        self.settings_summary_label.setText("\n".join(details))

    def _load_settings(self) -> None:
        self._loading_settings = True

        workspace = self.settings.value("workspace_dir", "", type=str)
        if workspace:
            self.config.workspace_dir = Path(workspace)
            self.workspace_value_label.setText(str(self.config.workspace_dir))

        start_mode = self.settings.value("start_mode", "pdfs", type=str)
        start_mode_index = self.start_mode_combo.findData(start_mode)
        if start_mode_index >= 0:
            self.start_mode_combo.setCurrentIndex(start_mode_index)

        existing_marker_root = self.settings.value("existing_marker_root", "", type=str)
        if existing_marker_root:
            self.existing_marker_root_input.setText(existing_marker_root)

        resume_stage = self.settings.value("resume_stage", PipelineStage.TRIAGE.name, type=str)
        resume_stage_index = self.resume_stage_combo.findData(resume_stage)
        if resume_stage_index >= 0:
            self.resume_stage_combo.setCurrentIndex(resume_stage_index)

        language_code = self.settings.value("language", "en", type=str)
        language_index = self.language_combo.findData(language_code)
        if language_index >= 0:
            self.language_combo.setCurrentIndex(language_index)

        use_cloud = self.settings.value("use_cloud_descriptions", True, type=bool)
        self.describe_checkbox.setChecked(use_cloud)
        self.llm_api_base_input.setText(
            self.settings.value("llm_api_base", self.config.default_llm_api_base, type=str)
        )
        self.llm_model_input.setText(
            self.settings.value("llm_model", self.config.default_llm_model, type=str)
        )

        remember_api_key = self.settings.value("remember_api_key", False, type=bool)
        self.remember_api_key_checkbox.setChecked(remember_api_key)
        if remember_api_key:
            self.llm_api_key_input.setText(load_api_key(self.config))

        self.additional_caption_labels_input.setPlainText(
            self.settings.value("additional_caption_labels", "", type=str)
        )

        self._loading_settings = False
        self._update_start_mode_ui()

    def _save_settings(self) -> None:
        if self._loading_settings:
            return
        self.settings.setValue("workspace_dir", str(self.config.workspace_dir))
        self.settings.setValue("start_mode", self._current_start_mode())
        self.settings.setValue(
            "existing_marker_root", self.existing_marker_root_input.text().strip()
        )
        self.settings.setValue("resume_stage", self.resume_stage_combo.currentData())
        self.settings.setValue("language", self.language_combo.currentData())
        self.settings.setValue("use_cloud_descriptions", self.describe_checkbox.isChecked())
        self.settings.setValue("llm_api_base", self.llm_api_base_input.text().strip())
        self.settings.setValue("llm_model", self.llm_model_input.text().strip())
        self.settings.setValue("remember_api_key", self.remember_api_key_checkbox.isChecked())
        self.settings.setValue(
            "additional_caption_labels", self.additional_caption_labels_input.toPlainText()
        )
        self._update_settings_summary()
