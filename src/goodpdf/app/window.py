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

from goodpdf.pipeline.jobs import JobRequest, JobResult, PIPELINE_STAGES, language_options
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

        self.describe_checkbox = QCheckBox("Enable cloud image descriptions")
        self.describe_checkbox.setChecked(True)
        self.describe_checkbox.toggled.connect(self._handle_cloud_toggle)
        self.describe_checkbox.toggled.connect(self._save_settings)

        self.settings_summary_label = QLabel()
        self.settings_summary_label.setWordWrap(True)
        self.settings_summary_label.setStyleSheet("color: #666;")

        job_layout.addWidget(language_label)
        job_layout.addWidget(self.language_combo)
        job_layout.addWidget(self.describe_checkbox)
        job_layout.addWidget(self.settings_summary_label)

        pdf_group = QGroupBox("PDFs")
        pdf_layout = QVBoxLayout(pdf_group)
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
        layout.addWidget(pdf_group, stretch=1)
        layout.addWidget(progress_group, stretch=1)
        layout.addLayout(actions)
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

        cloud_layout.addWidget(api_base_label)
        cloud_layout.addWidget(self.llm_api_base_input)
        cloud_layout.addWidget(model_label)
        cloud_layout.addWidget(self.llm_model_input)
        cloud_layout.addWidget(key_label)
        cloud_layout.addWidget(self.llm_api_key_input)
        cloud_layout.addWidget(self.remember_api_key_checkbox)
        cloud_layout.addWidget(cloud_hint)

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

        request = JobRequest(
            source_pdfs=self.selected_pdfs,
            language=self.language_combo.currentData(),
            use_cloud_descriptions=self.describe_checkbox.isChecked(),
            output_root=self.config.workspace_dir,
            llm_model=self.llm_model_input.text().strip() or self.config.default_llm_model,
            llm_api_key=self.llm_api_key_input.text().strip() or None,
            llm_api_base=self.llm_api_base_input.text().strip() or None,
        )
        try:
            request.validated_pdfs()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid PDF selection", str(exc))
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
        self.language_combo.setEnabled(enabled)
        self.describe_checkbox.setEnabled(enabled)
        self.llm_api_base_input.setEnabled(cloud_enabled)
        self.llm_model_input.setEnabled(cloud_enabled)
        self.llm_api_key_input.setEnabled(cloud_enabled)
        self.remember_api_key_checkbox.setEnabled(cloud_enabled)
        self.choose_workspace_button.setEnabled(enabled)
        self.add_pdfs_button.setEnabled(enabled)
        self.remove_selected_button.setEnabled(enabled)
        self.clear_all_button.setEnabled(enabled)
        self.run_button.setEnabled(enabled)

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
        self.settings_summary_label.setText(
            f"Workspace: {self.config.workspace_dir}\n{cloud_mode} | {provider_text}"
        )

    def _load_settings(self) -> None:
        self._loading_settings = True

        workspace = self.settings.value("workspace_dir", "", type=str)
        if workspace:
            self.config.workspace_dir = Path(workspace)
            self.workspace_value_label.setText(str(self.config.workspace_dir))

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

        self._loading_settings = False

    def _save_settings(self) -> None:
        if self._loading_settings:
            return
        self.settings.setValue("workspace_dir", str(self.config.workspace_dir))
        self.settings.setValue("language", self.language_combo.currentData())
        self.settings.setValue("use_cloud_descriptions", self.describe_checkbox.isChecked())
        self.settings.setValue("llm_api_base", self.llm_api_base_input.text().strip())
        self.settings.setValue("llm_model", self.llm_model_input.text().strip())
        self.settings.setValue("remember_api_key", self.remember_api_key_checkbox.isChecked())
        self._update_settings_summary()
