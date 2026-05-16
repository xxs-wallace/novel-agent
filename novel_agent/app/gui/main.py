from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from novel_agent.app.bootstrap import resolve_repo_root
from novel_agent.app.cli import WriterStatusPresenter
from novel_agent.app.gui.interactive_runner import (
    GuiRunCommand,
    InteractivePipelineCommand,
    PipelineRunConfig,
    WriterRunConfig,
    WriterWorkflowCommand,
)


def _import_qt() -> tuple[object, object, object]:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
    except ModuleNotFoundError as exc:
        raise SystemExit("未安装 PySide6。请先运行：python -m pip install -e '.[gui]'") from exc
    return QtCore, QtGui, QtWidgets


QtCore, QtGui, QtWidgets = _import_qt()


class PipelineWorker(QtCore.QObject):
    log_received = QtCore.Signal(str)
    finished = QtCore.Signal(int)
    failed = QtCore.Signal(str)

    def __init__(self, command: GuiRunCommand) -> None:
        super().__init__()
        self._command = command
        self._process: subprocess.Popen[bytes] | None = None

    @QtCore.Slot()
    def run(self) -> None:
        try:
            process = subprocess.Popen(
                self._command.command(),
                cwd=str(self._command.working_directory()),
                env=self._command.environment(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self._process = process
            if process.stdin is not None:
                process.stdin.write(self._command.stdin_payload())
                process.stdin.close()
            if process.stdout is not None:
                for line in iter(process.stdout.readline, b""):
                    self.log_received.emit(line.decode("utf-8", errors="replace"))
            self.finished.emit(process.wait())
        except Exception as exc:  # noqa: BLE001 - surface prototype failures in the GUI.
            self.failed.emit(str(exc))

    def terminate(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()


class ListInput(QtWidgets.QWidget):
    def __init__(self, placeholder: str) -> None:
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        input_row = QtWidgets.QHBoxLayout()
        input_row.setSpacing(8)
        self.input = QtWidgets.QLineEdit()
        self.input.setPlaceholderText(placeholder)
        self.input.returnPressed.connect(self._add_from_input)
        add_button = QtWidgets.QPushButton("添加")
        add_button.setObjectName("SecondaryButton")
        add_button.clicked.connect(self._add_from_input)
        input_row.addWidget(self.input)
        input_row.addWidget(add_button)
        layout.addLayout(input_row)

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setObjectName("ValueList")
        self.list_widget.setFixedHeight(74)
        layout.addWidget(self.list_widget)

        remove_button = QtWidgets.QPushButton("删除选中")
        remove_button.setObjectName("SecondaryButton")
        remove_button.clicked.connect(self._remove_selected)
        layout.addWidget(remove_button)

    def values(self) -> list[str]:
        return [
            self.list_widget.item(index).text().strip()
            for index in range(self.list_widget.count())
            if self.list_widget.item(index).text().strip()
        ]

    def values_text(self) -> str:
        return "\n".join(self.values())

    def _add_from_input(self) -> None:
        raw = self.input.text().strip()
        if not raw:
            return
        for item in self._split_items(raw):
            self.list_widget.addItem(item)
        self.input.clear()

    def _remove_selected(self) -> None:
        for item in self.list_widget.selectedItems():
            self.list_widget.takeItem(self.list_widget.row(item))

    @staticmethod
    def _split_items(value: str) -> list[str]:
        import re

        return [item.strip() for item in re.split(r"[,，;；\n]+", value) if item.strip()]


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, repo_root: Path) -> None:
        super().__init__()
        self._repo_root = repo_root
        self._thread: object | None = None
        self._worker: PipelineWorker | None = None
        self._active_mode = "pipeline"
        self._writer_action_override = ""
        self._writer_status_presenter = WriterStatusPresenter()
        self._env_api_key_available = bool(os.getenv("DEEPSEEK_API_KEY", "").strip())
        self.setWindowTitle("Novel Agent")
        self.resize(980, 640)
        self.setMinimumSize(760, 520)
        self._build_ui()
        self._apply_theme()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        central.setObjectName("AppRoot")
        layout = QtWidgets.QHBoxLayout(central)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)

        output_panel = QtWidgets.QWidget()
        output_panel.setObjectName("OutputPanel")
        output_layout = QtWidgets.QVBoxLayout(output_panel)
        output_layout.setContentsMargins(18, 16, 18, 18)
        output_layout.setSpacing(10)

        title = QtWidgets.QLabel("运行输出与审查文本")
        title.setObjectName("PanelTitle")
        subtitle = QtWidgets.QLabel("这里会实时显示 pipeline 日志、JSON 结果，以及后续审查阶段输出的小说文本。")
        subtitle.setObjectName("PanelSubtitle")
        output_layout.addWidget(title)
        output_layout.addWidget(subtitle)

        self.log_output = QtWidgets.QPlainTextEdit()
        self.log_output.setObjectName("LogOutput")
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth)
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(12)
        self.log_output.setFont(font)
        output_layout.addWidget(self.log_output, stretch=1)

        side_panel = QtWidgets.QWidget()
        side_panel.setObjectName("SidePanel")
        side_panel.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        side_layout = QtWidgets.QVBoxLayout(side_panel)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_layout.setSpacing(10)

        side_title = QtWidgets.QLabel("控制台")
        side_title.setObjectName("SideTitle")
        side_hint = QtWidgets.QLabel("选择一个功能界面，然后启动对应的 Python workflow。")
        side_hint.setObjectName("SideHint")
        side_hint.setWordWrap(True)
        side_layout.addWidget(side_title)
        side_layout.addWidget(side_hint)

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.setSpacing(10)
        self.pipeline_mode_button = QtWidgets.QPushButton("Pipeline")
        self.pipeline_mode_button.setObjectName("ModeButton")
        self.pipeline_mode_button.setCheckable(True)
        self.pipeline_mode_button.setChecked(True)
        self.writer_mode_button = QtWidgets.QPushButton("Writer")
        self.writer_mode_button.setObjectName("ModeButton")
        self.writer_mode_button.setCheckable(True)
        self.pipeline_mode_button.clicked.connect(lambda: self._set_mode("pipeline"))
        self.writer_mode_button.clicked.connect(lambda: self._set_mode("writer"))
        mode_row.addWidget(self.pipeline_mode_button)
        mode_row.addWidget(self.writer_mode_button)
        side_layout.addLayout(mode_row)

        self.mode_stack = QtWidgets.QStackedWidget()
        self.mode_stack.addWidget(self._build_pipeline_page())
        self.mode_stack.addWidget(self._build_writer_page())
        self.mode_scroll = QtWidgets.QScrollArea()
        self.mode_scroll.setObjectName("ModeScroll")
        self.mode_scroll.setWidgetResizable(True)
        self.mode_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.mode_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.mode_scroll.setWidget(self.mode_stack)
        side_layout.addWidget(self.mode_scroll, stretch=1)

        self.run_button = QtWidgets.QPushButton("启动 Pipeline")
        self.run_button.setObjectName("PrimaryButton")
        self.stop_button = QtWidgets.QPushButton("停止")
        self.stop_button.setObjectName("DangerButton")
        self.stop_button.setEnabled(False)
        self.run_button.clicked.connect(self._start_run)
        self.stop_button.clicked.connect(self._stop_run)
        button_row = QtWidgets.QHBoxLayout()
        button_row.setSpacing(10)
        button_row.addWidget(self.run_button)
        button_row.addWidget(self.stop_button)
        side_layout.addLayout(button_row)

        self.status_label = QtWidgets.QLabel("Pipeline 模式，等待启动")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)
        side_layout.addWidget(self.status_label)

        layout.addWidget(output_panel, stretch=1)
        layout.addWidget(side_panel, stretch=0)

        self.setCentralWidget(central)

    def _new_form(self) -> object:
        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 8, 0, 0)
        form.setSpacing(10)
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        return form

    def _build_pipeline_page(self) -> object:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        section_title = QtWidgets.QLabel("导入原文 / 阅读 Pipeline")
        section_title.setObjectName("SectionTitle")
        layout.addWidget(section_title)

        form = self._new_form()
        self.task_name_input = QtWidgets.QLineEdit("couple-smoke")
        self.source_path_input = QtWidgets.QLineEdit(str(self._repo_root / "couple.txt"))
        browse_button = QtWidgets.QPushButton("选择")
        browse_button.setObjectName("SecondaryButton")
        browse_button.clicked.connect(self._select_source_path)
        path_row = QtWidgets.QHBoxLayout()
        path_row.setSpacing(8)
        path_row.addWidget(self.source_path_input)
        path_row.addWidget(browse_button)

        self.api_key_input = QtWidgets.QLineEdit()
        self.api_key_input.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.api_key_status_label = QtWidgets.QLabel("已从环境变量 DEEPSEEK_API_KEY 读取")
        self.api_key_status_label.setObjectName("EnvStatusLabel")
        self.api_key_input.setVisible(not self._env_api_key_available)
        self.api_key_status_label.setVisible(self._env_api_key_available)
        self.run_mode_input = QtWidgets.QComboBox()
        self.run_mode_input.addItems(["fresh", "resume"])
        self.max_read_input = QtWidgets.QSpinBox()
        self.max_read_input.setRange(1, 1024 * 1024)
        self.max_read_input.setValue(50)
        self.max_close_input = QtWidgets.QSpinBox()
        self.max_close_input.setRange(1, 10000)
        self.max_close_input.setValue(12)
        self.segment_step_input = QtWidgets.QSpinBox()
        self.segment_step_input.setRange(1, 1024 * 1024)
        self.segment_step_input.setValue(32)
        self.close_step_input = QtWidgets.QSpinBox()
        self.close_step_input.setRange(1, 10000)
        self.close_step_input.setValue(1)
        self.creative_kb_input = QtWidgets.QCheckBox("构建 Creative KB")
        self.creative_kb_input.setChecked(True)

        form.addRow("任务名称", self.task_name_input)
        form.addRow("小说路径", path_row)
        form.addRow("DeepSeek API Key", self.api_key_status_label if self._env_api_key_available else self.api_key_input)
        form.addRow("运行模式", self.run_mode_input)
        form.addRow("导入原文上限 KB", self.max_read_input)
        form.addRow("阅读轮数", self.max_close_input)
        form.addRow("导入原文步长 KB", self.segment_step_input)
        form.addRow("阅读步长 batch", self.close_step_input)
        form.addRow("", self.creative_kb_input)
        layout.addLayout(form)
        return page

    def _build_writer_page(self) -> object:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        section_title = QtWidgets.QLabel("Writer 分层工作流")
        section_title.setObjectName("SectionTitle")
        layout.addWidget(section_title)

        form = self._new_form()
        self.writer_task_name_input = QtWidgets.QLineEdit("writer-smoke")
        self.writer_api_key_input = QtWidgets.QLineEdit()
        self.writer_api_key_input.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.writer_api_key_status_label = QtWidgets.QLabel("已从环境变量 DEEPSEEK_API_KEY 读取")
        self.writer_api_key_status_label.setObjectName("EnvStatusLabel")
        self.writer_api_key_input.setVisible(not self._env_api_key_available)
        self.writer_api_key_status_label.setVisible(self._env_api_key_available)
        self.writer_dry_run_input = QtWidgets.QCheckBox("dry-run")
        self.writer_dry_run_input.setChecked(True)
        self.writer_product_mode_input = QtWidgets.QComboBox()
        self.writer_product_mode_input.addItems(["assist", "batch", "auto_novel"])
        self.writer_action_input = QtWidgets.QComboBox()
        self.writer_action_input.addItems(
            [
                "guided",
                "initialize",
                "prepare_planning",
                "continue_after_planning_review",
                "prepare_batch_plan",
                "continue_after_batch_review",
                "prepare_chapter_package",
                "continue_after_chapter_review",
                "resume",
                "prepare_chapter_length_plan",
                "continue_after_length_review",
                "prepare_execution",
                "continue_after_execution_review",
                "execute_current_chapter",
                "accept_chapter",
                "discard_chapter",
                "approve_writeback",
            ]
        )
        self.writer_run_id_input = QtWidgets.QLineEdit("writer-smoke")
        self.writer_major_characters_input = ListInput("输入角色名后点添加；也可粘贴逗号分隔内容")
        self.writer_desired_actions_input = ListInput("输入动作目标后点添加")
        self.writer_avoidances_input = ListInput("输入禁止内容后点添加")
        self.writer_preferred_outcome_input = QtWidgets.QLineEdit()
        self.writer_notes_input = QtWidgets.QLineEdit()
        self.writer_world_notes_input = QtWidgets.QLineEdit()
        self.writer_target_chapter_count_input = QtWidgets.QSpinBox()
        self.writer_target_chapter_count_input.setRange(1, 1000)
        self.writer_target_chapter_count_input.setValue(3)
        self.writer_chapter_count_input = QtWidgets.QSpinBox()
        self.writer_chapter_count_input.setRange(1, 1000)
        self.writer_chapter_count_input.setValue(3)
        self.writer_chapter_id_input = QtWidgets.QLineEdit()
        self.writer_chapter_id_input.setPlaceholderText("留空自动选择第一章；也可填 batch15-ch01 / 1 / 一")
        self.writer_allow_incomplete_input = QtWidgets.QCheckBox("建模未完成也继续")
        self.writer_allow_incomplete_input.setChecked(True)
        self.writer_execute_chapter_input = QtWidgets.QCheckBox("确认本章写作输入后立刻生成正文")
        self.writer_execute_chapter_input.setChecked(False)
        self.writer_reset_memory_input = QtWidgets.QCheckBox("重置 Writer 独立 memory 副本")
        self.writer_reset_memory_input.setChecked(False)

        form.addRow("任务名称", self.writer_task_name_input)
        form.addRow(
            "DeepSeek API Key",
            self.writer_api_key_status_label if self._env_api_key_available else self.writer_api_key_input,
        )
        form.addRow("", self.writer_dry_run_input)
        form.addRow("产品模式", self.writer_product_mode_input)
        form.addRow("动作", self.writer_action_input)
        form.addRow("run_id", self.writer_run_id_input)
        form.addRow("主要角色", self.writer_major_characters_input)
        form.addRow("动作目标", self.writer_desired_actions_input)
        form.addRow("避免项", self.writer_avoidances_input)
        form.addRow("期望结果", self.writer_preferred_outcome_input)
        form.addRow("补充说明", self.writer_notes_input)
        form.addRow("世界观补充", self.writer_world_notes_input)
        form.addRow("批次章节数", self.writer_target_chapter_count_input)
        form.addRow("梗概章节数", self.writer_chapter_count_input)
        form.addRow("chapter_id", self.writer_chapter_id_input)
        form.addRow("", self.writer_allow_incomplete_input)
        form.addRow("", self.writer_execute_chapter_input)
        form.addRow("", self.writer_reset_memory_input)
        layout.addLayout(form)

        state_title = QtWidgets.QLabel("状态机操作")
        state_title.setObjectName("SectionTitle")
        layout.addWidget(state_title)
        refresh_button = QtWidgets.QPushButton("刷新状态")
        refresh_button.setObjectName("SecondaryButton")
        refresh_button.clicked.connect(self._refresh_writer_state_buttons)
        layout.addWidget(refresh_button)
        self.writer_state_label = QtWidgets.QLabel("填写 run_id 后刷新状态")
        self.writer_state_label.setObjectName("StatusLabel")
        self.writer_state_label.setWordWrap(True)
        layout.addWidget(self.writer_state_label)
        self.writer_state_buttons_layout = QtWidgets.QVBoxLayout()
        self.writer_state_buttons_layout.setSpacing(8)
        layout.addLayout(self.writer_state_buttons_layout)
        self._refresh_writer_state_buttons()
        return page

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            #AppRoot {
                background: #f6f8fb;
                color: #334155;
            }
            #OutputPanel,
            #SidePanel {
                background: #ffffff;
                border: 1px solid #e4eaf2;
                border-radius: 18px;
            }
            #SidePanel {
                min-width: 280px;
                max-width: 420px;
            }
            #PanelTitle,
            #SideTitle {
                color: #1f2937;
                font-size: 20px;
                font-weight: 700;
            }
            #SectionTitle {
                color: #526071;
                font-size: 15px;
                font-weight: 700;
                padding-top: 4px;
            }
            #PanelSubtitle,
            #SideHint,
            #StatusLabel,
            #EnvStatusLabel {
                color: #8a96a8;
                font-size: 13px;
            }
            #EnvStatusLabel {
                background: #eef7f1;
                border: 1px solid #d7eadc;
                border-radius: 12px;
                color: #6c9276;
                padding: 8px 10px;
            }
            #ModeScroll {
                background: transparent;
                border: none;
            }
            QScrollArea,
            QScrollArea > QWidget,
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 2px 0 2px 0;
            }
            QScrollBar::handle:vertical {
                background: #d6e0eb;
                border-radius: 4px;
                min-height: 32px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0;
            }
            QLabel {
                color: #738195;
                font-size: 13px;
            }
            QLineEdit,
            QComboBox,
            QSpinBox {
                background: #f9fbfe;
                border: 1px solid #dce4ef;
                border-radius: 12px;
                color: #475569;
                padding: 8px 10px;
                min-height: 22px;
            }
            QLineEdit:focus,
            QComboBox:focus,
            QSpinBox:focus {
                border: 1px solid #9db7e8;
                background: #ffffff;
            }
            #ValueList {
                background: #fbfdff;
                border: 1px solid #dce4ef;
                border-radius: 12px;
                color: #526071;
                padding: 4px;
            }
            #ValueList::item {
                padding: 4px 6px;
                border-radius: 8px;
            }
            #ValueList::item:selected {
                background: #dceafe;
                color: #334155;
            }
            QCheckBox {
                color: #667085;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 5px;
                border: 1px solid #cbd5e1;
                background: #ffffff;
            }
            QCheckBox::indicator:checked {
                background: #7ea6e0;
                border: 1px solid #7ea6e0;
            }
            QPushButton {
                border: none;
                border-radius: 16px;
                padding: 10px 16px;
                min-height: 28px;
                font-weight: 600;
            }
            QPushButton:disabled {
                background: #e8edf5;
                color: #a8b3c4;
            }
            #PrimaryButton {
                background: #86aee7;
                color: #ffffff;
            }
            #PrimaryButton:hover {
                background: #769fdb;
            }
            #SecondaryButton {
                background: #eef4fb;
                color: #6b83a6;
            }
            #SecondaryButton:hover {
                background: #e3edf8;
            }
            #ModeButton {
                background: #f1f5fa;
                color: #8290a3;
                border: 1px solid #e3eaf2;
            }
            #ModeButton:checked {
                background: #86aee7;
                color: #ffffff;
                border: 1px solid #86aee7;
            }
            #DangerButton {
                background: #f5d6d6;
                color: #a45d5d;
            }
            #DangerButton:hover {
                background: #efc7c7;
            }
            #LogOutput {
                background: #fbfdff;
                border: 1px solid #dde7f1;
                border-radius: 14px;
                color: #4b5563;
                padding: 12px;
                selection-background-color: #cadcf6;
            }
            QPlainTextEdit {
                line-height: 1.45;
            }
            """
        )

    def _select_source_path(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择小说文件", str(self._repo_root))
        if path:
            self.source_path_input.setText(path)

    def _set_mode(self, mode: str) -> None:
        self._active_mode = mode
        is_pipeline = mode == "pipeline"
        self.mode_stack.setCurrentIndex(0 if is_pipeline else 1)
        self.pipeline_mode_button.setChecked(is_pipeline)
        self.writer_mode_button.setChecked(not is_pipeline)
        self.run_button.setText("启动 Pipeline" if is_pipeline else "启动 Writer")
        self.status_label.setText(("Pipeline" if is_pipeline else "Writer") + " 模式，等待启动")
        if not is_pipeline:
            self._refresh_writer_state_buttons()

    def _pipeline_config_from_form(self) -> PipelineRunConfig:
        return PipelineRunConfig(
            repo_root=self._repo_root,
            task_name=self.task_name_input.text(),
            source_path=Path(self.source_path_input.text()),
            run_mode=self.run_mode_input.currentText(),
            max_read_kb=self.max_read_input.value(),
            max_close_batches=self.max_close_input.value(),
            segment_step_kb=self.segment_step_input.value(),
            close_step_batches=self.close_step_input.value(),
            build_creative_kb=self.creative_kb_input.isChecked(),
            api_key=self.api_key_input.text(),
        )

    def _writer_config_from_form(self) -> WriterRunConfig:
        return WriterRunConfig(
            repo_root=self._repo_root,
            task_name=self.writer_task_name_input.text(),
            dry_run=self.writer_dry_run_input.isChecked(),
            api_key=self.writer_api_key_input.text(),
            product_mode=self.writer_product_mode_input.currentText(),
            action=self._writer_action_override or self.writer_action_input.currentText(),
            run_id=self.writer_run_id_input.text(),
            major_characters=self.writer_major_characters_input.values_text(),
            desired_actions=self.writer_desired_actions_input.values_text(),
            avoidances=self.writer_avoidances_input.values_text(),
            preferred_outcome=self.writer_preferred_outcome_input.text(),
            notes=self.writer_notes_input.text(),
            user_world_notes=self.writer_world_notes_input.text(),
            target_chapter_count=self.writer_target_chapter_count_input.value(),
            chapter_count=self.writer_chapter_count_input.value(),
            chapter_id=self.writer_chapter_id_input.text(),
            allow_incomplete_modeling=self.writer_allow_incomplete_input.isChecked(),
            execute_chapter=self.writer_execute_chapter_input.isChecked(),
            reset_writer_memory=self.writer_reset_memory_input.isChecked(),
        )

    def _command_from_active_mode(self) -> GuiRunCommand:
        if self._active_mode == "writer":
            return WriterWorkflowCommand(self._writer_config_from_form())
        return InteractivePipelineCommand(self._pipeline_config_from_form())

    def _refresh_writer_state_buttons(self) -> None:
        if not hasattr(self, "writer_state_buttons_layout"):
            return
        self._clear_layout(self.writer_state_buttons_layout)
        state = self._load_writer_state()
        stage = str((state or {}).get("current_stage") or "not_initialized")
        pending = dict((state or {}).get("pending_checkpoint") or {})
        pending_stage = str(pending.get("stage") or "")
        terminal = dict((state or {}).get("terminal_stage") or {})
        if terminal:
            terminal_status = self._writer_status_presenter.present(str(terminal.get("stage") or stage))
            self.writer_state_label.setText(
                f"当前步骤：{terminal_status.step}"
                + (f"\n说明：{terminal_status.message}" if terminal_status.message else "")
            )
        elif pending_stage:
            status = self._writer_status_presenter.present(pending_stage)
            self.writer_state_label.setText(
                f"当前步骤：{status.step}"
                + (f"\n说明：{status.message}" if status.message else "")
            )
        else:
            status = self._writer_status_presenter.present(stage)
            self.writer_state_label.setText(
                f"当前步骤：{status.step}"
                + (f"\n下一步：{status.next_action}" if status.next_action else "")
            )

        for label, action in self._writer_actions_for_stage(stage=stage, pending_stage=pending_stage):
            button = QtWidgets.QPushButton(label)
            button.setObjectName("SecondaryButton")
            button.clicked.connect(lambda _checked=False, selected_action=action: self._start_writer_action(selected_action))
            self.writer_state_buttons_layout.addWidget(button)

    def _writer_actions_for_stage(self, *, stage: str, pending_stage: str) -> list[tuple[str, str]]:
        return [
            (action.label, action.workflow_action)
            for action in self._writer_status_presenter.writer_actions_for_stage(
                stage=stage,
                pending_stage=pending_stage,
            )
        ]

    def _load_writer_state(self) -> dict[str, object] | None:
        run_id = self.writer_run_id_input.text().strip()
        if not run_id:
            return None
        path = self._repo_root / "runs" / "writer" / run_id / "workflow_state.json"
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        payload = raw.get("data") if isinstance(raw, dict) else raw
        return dict(payload) if isinstance(payload, dict) else None

    def _start_writer_action(self, action: str) -> None:
        self._writer_action_override = action
        self._start_run()

    def _clear_layout(self, layout: object) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _start_run(self) -> None:
        command = self._command_from_active_mode()
        self._writer_action_override = ""
        try:
            command.stdin_payload()
            command.validate_runtime()
        except (RuntimeError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, "参数错误", str(exc))
            self.status_label.setText("启动前检查失败")
            return

        self.log_output.clear()
        self._append_log("$ " + " ".join(command.command()) + "\n")
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("正在运行")

        thread = QtCore.QThread(self)
        worker = PipelineWorker(command)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.log_received.connect(self._append_log)
        worker.failed.connect(self._run_failed)
        worker.finished.connect(self._run_finished)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        self._thread = thread
        self._worker = worker

    def _stop_run(self) -> None:
        if self._worker is not None:
            self._worker.terminate()
            self._append_log("\n已请求停止当前任务。\n")

    def _append_log(self, text: str) -> None:
        self.log_output.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        self.log_output.insertPlainText(text)
        self.log_output.moveCursor(QtGui.QTextCursor.MoveOperation.End)

    def _run_failed(self, message: str) -> None:
        self._append_log(f"\n运行失败：{message}\n")
        self.status_label.setText("运行失败")
        self._reset_buttons()

    def _run_finished(self, exit_code: int) -> None:
        self._append_log(f"\n进程退出，状态码：{exit_code}\n")
        self.status_label.setText("已完成" if exit_code == 0 else f"已退出，状态码：{exit_code}")
        self._reset_buttons()
        if self._active_mode == "writer":
            self._refresh_writer_state_buttons()

    def _reset_buttons(self) -> None:
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)


def main() -> int:
    app = QtWidgets.QApplication([])
    window = MainWindow(resolve_repo_root())
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
