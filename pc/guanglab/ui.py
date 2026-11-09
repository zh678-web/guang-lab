"""光 · 实验室 PC 版 —— Qt 桌面界面。

布局：顶部设备栏 / 左侧应用列表 / 右侧工作区（一键授权、应用操作、终端）
      / 底部执行结果与日志。所有 adb 调用都放在工作线程，界面不卡死。
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Callable

from PySide6.QtCore import Qt, QSettings, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QStackedWidget, QStatusBar,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from . import __version__, core
from .adb import Adb, AdbError, Device, find_adb
from .labels import LabelResolver, find_aapt2

APP_TITLE = "光 · 实验室  ·  PC 版"

QSS = """
QWidget { font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
          font-size: 10pt; color: #1f2329; }
QMainWindow, QDialog { background: #f5f6f8; }
QGroupBox { background: #ffffff; border: 1px solid #e3e6ec; border-radius: 8px;
            margin-top: 14px; padding: 12px 10px 10px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px;
                   color: #5b6472; font-weight: 600; }
QPushButton { background: #ffffff; border: 1px solid #d8dce4; border-radius: 6px;
              padding: 6px 12px; min-height: 18px; }
QPushButton:hover { border-color: #2f6feb; color: #2f6feb; }
QPushButton:pressed { background: #eef3ff; }
QPushButton:disabled { color: #a8adb8; border-color: #e8eaee; background: #fafbfc; }
QPushButton[accent="true"] { background: #2f6feb; color: #ffffff; border-color: #2f6feb; font-weight: 600; }
QPushButton[accent="true"]:hover { background: #2560d0; color: #ffffff; }
QPushButton[danger="true"] { color: #c5221f; border-color: #f0c7c4; }
QPushButton[danger="true"]:hover { background: #fff3f2; color: #c5221f; }
QLineEdit, QComboBox, QPlainTextEdit, QListWidget, QTableWidget {
    background: #ffffff; border: 1px solid #dfe3e9; border-radius: 6px;
    selection-background-color: #e3edff; selection-color: #1f2329; }
QLineEdit, QComboBox { padding: 5px 8px; }
QTableWidget { gridline-color: #eef0f4; }
QHeaderView::section { background: #f3f5f8; border: none; border-right: 1px solid #e8ebf0;
                       padding: 7px 8px; color: #4a5260; font-weight: 600; }
QTabWidget::pane { border: 1px solid #e3e6ec; border-radius: 8px; background: #ffffff; }
QTabBar::tab { padding: 8px 18px; color: #5b6472; }
QTabBar::tab:selected { color: #2f6feb; font-weight: 600; }
QStatusBar { background: #ffffff; border-top: 1px solid #e3e6ec; color: #5b6472; }
QSplitter::handle { background: #e8ebf0; }
QLabel[hint="true"] { color: #7a8290; }
QLabel[warn="true"] { color: #b06000; background: #fff7e8;
                      border: 1px solid #f5dfb8; border-radius: 6px; padding: 7px 9px; }
"""

# 这些动作与具体应用无关，未选中应用时用占位包名（op_script 仍要求合法包名）
NO_PKG_ACTIONS = frozenset({
    "gray_on", "gray_off", "server_state", "scan_adb", "install_priv", "brevent_up",
})
PLACEHOLDER_PKG = "android"

STATE_COLORS = {
    "ok": QColor("#e8f5ec"),
    "skip": QColor("#fff5e0"),
    "fail": QColor("#fdeaea"),
}
STATE_TEXT = {"ok": "成功", "skip": "跳过", "fail": "失败"}


class Worker(QThread):
    """把一次阻塞的 adb 调用放到子线程。"""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as e:  # noqa: BLE001 - 子线程异常必须全部回传主线程
            self.failed.emit(f"{type(e).__name__}: {e}")


class SettingsDialog(QDialog):
    def __init__(self, parent, adb_path: str, aapt2_path: str):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(520)
        form = QFormLayout(self)
        form.setSpacing(10)
        form.setContentsMargins(18, 18, 18, 18)

        self.adb_edit = QLineEdit(adb_path)
        adb_row = QHBoxLayout()
        adb_row.addWidget(self.adb_edit, 1)
        b1 = QPushButton("浏览…")
        b1.clicked.connect(lambda: self._pick(self.adb_edit, "adb.exe"))
        adb_row.addWidget(b1)
        w1 = QWidget(); w1.setLayout(adb_row)
        form.addRow("adb.exe 路径", w1)

        self.aapt_edit = QLineEdit(aapt2_path)
        aapt_row = QHBoxLayout()
        aapt_row.addWidget(self.aapt_edit, 1)
        b2 = QPushButton("浏览…")
        b2.clicked.connect(lambda: self._pick(self.aapt_edit, "aapt2.exe"))
        aapt_row.addWidget(b2)
        w2 = QWidget(); w2.setLayout(aapt_row)
        form.addRow("aapt2 路径（可选）", w2)

        note = QLabel("留空即自动探测 Android SDK。aapt2 只用于显示应用中文名，"
                      "没有它全部功能照常工作。")
        note.setWordWrap(True)
        note.setProperty("hint", True)
        form.addRow("", note)

        self.confirm_box = QCheckBox("危险操作（卸载 / 清数据 / 设备管理员）执行前二次确认")
        self.confirm_box.setChecked(parent.setting_confirm())
        form.addRow("", self.confirm_box)

        self.autoswitch_box = QCheckBox("执行完成后自动切到「执行结果」")
        self.autoswitch_box.setChecked(parent.setting_autoswitch())
        form.addRow("", self.autoswitch_box)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("保存")
        ok.setProperty("accent", True)
        ok.clicked.connect(self.accept)
        row.addWidget(cancel); row.addWidget(ok)
        form.addRow("", self._wrap(row))

    @staticmethod
    def _wrap(layout):
        w = QWidget(); w.setLayout(layout); return w

    def _pick(self, edit: QLineEdit, name: str):
        path, _ = QFileDialog.getOpenFileName(self, f"选择 {name}", "", "可执行文件 (*.exe);;所有文件 (*)")
        if path:
            edit.setText(path)

    def values(self) -> tuple[str, str, bool, bool]:
        return (self.adb_edit.text().strip(), self.aapt_edit.text().strip(),
                self.confirm_box.isChecked(), self.autoswitch_box.isChecked())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE}  v{__version__}")
        self.resize(1180, 790)
        self.setStyleSheet(QSS)

        self.settings = QSettings("GuangLab", "GuangLabPC")
        self.adb: Adb | None = None
        self.devices: list[Device] = []
        self.serial: str = ""
        self.inventory: dict[str, set[str]] = {}
        self.dangerous: set[str] = set()
        self.target: core.Target | None = None
        self.labels: LabelResolver | None = None
        self.apps: list[tuple[str, str, str, str]] = []  # pkg, label, kind, state
        self.workers: list[Worker] = []

        self._build_ui()
        # --gui-smoke：只构造窗口、不连设备、不弹免责声明，用于打包后的界面自检
        if os.environ.get("GUANGLAB_SMOKE") == "1":
            self.status_label.setText("界面自检模式（未连接设备）")
        else:
            self._init_adb()
            if not self.settings.value("greeted", False, bool):
                self._show_disclaimer()

    # ------------------------------------------------------------- 设置项

    def setting_confirm(self) -> bool:
        return self.settings.value("confirm_danger", True, bool)

    def setting_autoswitch(self) -> bool:
        return self.settings.value("autoswitch", True, bool)

    def setting_adb_path(self) -> str:
        return self.settings.value("adb_path", "", str)

    def setting_aapt2_path(self) -> str:
        return self.settings.value("aapt2_path", "", str)

    # ------------------------------------------------------------- UI 构建

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 8)
        root.setSpacing(9)

        root.addWidget(self._build_device_bar())

        top = QWidget()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        left = self._build_app_panel()
        right = QTabWidget()
        right.addTab(self._build_grant_tab(), "一键授权")
        right.addTab(self._build_actions_tab(), "应用操作")
        right.addTab(self._build_terminal_tab(), "Shell 终端")
        self.work_tabs = right

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([480, 680])
        top_layout.addWidget(splitter)

        bottom = QTabWidget()
        bottom.addTab(self._build_result_tab(), "执行结果")
        bottom.addTab(self._build_log_tab(), "运行日志")
        self.bottom_tabs = bottom
        bottom.setMinimumHeight(190)

        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(top)
        vsplit.addWidget(bottom)
        vsplit.setStretchFactor(0, 7)
        vsplit.setStretchFactor(1, 3)
        vsplit.setSizes([470, 250])
        root.addWidget(vsplit, 1)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status_label = QLabel("未连接设备")
        self.status.addWidget(self.status_label, 1)
        self.identity_label = QLabel("")
        self.status.addPermanentWidget(self.identity_label)

    def _build_device_bar(self) -> QWidget:
        bar = QGroupBox()
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 12, 12, 10)
        h.setSpacing(8)

        h.addWidget(QLabel("设备"))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(270)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        h.addWidget(self.device_combo)

        self.btn_refresh_dev = QPushButton("刷新")
        self.btn_refresh_dev.setToolTip("重新枚举 adb devices")
        self.btn_refresh_dev.clicked.connect(self.refresh_devices)
        h.addWidget(self.btn_refresh_dev)

        self.btn_wifi = QPushButton("WiFi 连接…")
        self.btn_wifi.setToolTip("输入 手机IP:端口，先用 USB 执行过一次 adb tcpip 5555")
        self.btn_wifi.clicked.connect(self._wifi_connect)
        h.addWidget(self.btn_wifi)

        self.root_box = QCheckBox("root 模式 (su -c)")
        self.root_box.setToolTip("设备已 root 时勾选；普通 adb shell 已是 uid=2000(shell)，通常不需要")
        h.addWidget(self.root_box)

        h.addStretch(1)
        self.btn_settings = QPushButton("设置")
        self.btn_settings.clicked.connect(self._open_settings)
        h.addWidget(self.btn_settings)
        return bar

    def _build_app_panel(self) -> QWidget:
        box = QGroupBox("应用列表")
        v = QVBoxLayout(box)
        v.setSpacing(8)

        row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索包名 / 应用名…")
        self.search_edit.textChanged.connect(self._fill_app_table)
        row.addWidget(self.search_edit, 1)
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["全部", "第三方", "系统", "已冻结", "已卸载"])
        self.filter_combo.currentIndexChanged.connect(self._fill_app_table)
        row.addWidget(self.filter_combo)
        v.addLayout(row)

        self.app_table = QTableWidget(0, 4)
        self.app_table.setHorizontalHeaderLabels(["应用", "包名", "类型", "状态"])
        self.app_table.verticalHeader().setVisible(False)
        self.app_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.app_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.app_table.setAlternatingRowColors(False)
        hh = self.app_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.app_table.currentCellChanged.connect(self._on_app_selected)
        v.addWidget(self.app_table, 1)

        self.app_count = QLabel("尚未加载")
        self.app_count.setProperty("hint", True)
        v.addWidget(self.app_count)

        brow = QHBoxLayout()
        self.btn_refresh_apps = QPushButton("刷新应用")
        self.btn_refresh_apps.setProperty("accent", True)
        self.btn_refresh_apps.clicked.connect(self.refresh_apps)
        brow.addWidget(self.btn_refresh_apps)
        self.btn_resolve_label = QPushButton("解析当前应用名")
        self.btn_resolve_label.setToolTip("用本机 aapt2 读取 APK 的 application-label")
        self.btn_resolve_label.clicked.connect(self._resolve_current_label)
        brow.addWidget(self.btn_resolve_label)
        brow.addStretch(1)
        v.addLayout(brow)
        return box

    def _build_grant_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(9)

        head = QHBoxLayout()
        self.grant_target = QLabel("未选择应用")
        self.grant_target.setStyleSheet("font-weight:600; font-size:11pt;")
        head.addWidget(self.grant_target, 1)
        b = QPushButton("重新读取清单")
        b.setToolTip("dumpsys package 重新解析权限与三类组件")
        b.clicked.connect(self._reload_target)
        head.addWidget(b)
        v.addLayout(head)

        note = QLabel("按系统真值回读判定，不信退出码。AppOps 21 项、Shizuku 授权、"
                      "电池白名单由脚本固定处理；下面是可编辑的清单。")
        note.setWordWrap(True)
        note.setProperty("hint", True)
        v.addWidget(note)

        pl = QHBoxLayout()
        self.perm_list = QListWidget()
        self.perm_list.setMinimumHeight(150)
        pl.addWidget(self.perm_list, 1)
        col = QVBoxLayout()
        b1 = QPushButton("全选"); b1.clicked.connect(lambda: self._check_all(True))
        b2 = QPushButton("全不选"); b2.clicked.connect(lambda: self._check_all(False))
        col.addWidget(b1); col.addWidget(b2); col.addStretch(1)
        pl.addLayout(col)
        v.addLayout(pl, 1)

        form = QFormLayout()
        form.setSpacing(6)
        self.acc_edit = QLineEdit()
        self.nl_edit = QLineEdit()
        self.admin_edit = QLineEdit()
        for e in (self.acc_edit, self.nl_edit, self.admin_edit):
            e.setPlaceholderText("完整类名，多个用英文逗号分隔；留空表示不处理")
        form.addRow("无障碍服务", self.acc_edit)
        form.addRow("通知监听器", self.nl_edit)
        form.addRow("设备管理员", self.admin_edit)
        v.addLayout(form)

        row = QHBoxLayout()
        self.btn_grant = QPushButton("一键授权")
        self.btn_grant.setProperty("accent", True)
        self.btn_grant.clicked.connect(lambda: self._run_grant(False))
        self.btn_revoke = QPushButton("一键撤销")
        self.btn_revoke.setProperty("danger", True)
        self.btn_revoke.clicked.connect(lambda: self._run_grant(True))
        row.addWidget(self.btn_grant); row.addWidget(self.btn_revoke)
        row.addStretch(1)
        v.addLayout(row)
        return w

    def _build_actions_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)

        self.action_target = QLabel("未选择应用")
        self.action_target.setStyleSheet("font-weight:600;")
        v.addWidget(self.action_target)

        warn = QLabel("卸载、清除数据、设备管理员属于不可逆或高风险操作，执行前会二次确认。"
                      "所有动作都走同一套字符集校验与回执回读。")
        warn.setWordWrap(True)
        warn.setProperty("hint", True)
        v.addWidget(warn)

        grid = QGridLayout()
        grid.setSpacing(7)
        self.action_buttons: list[QPushButton] = []
        for i, (action, name, extra_kind, risk, tip) in enumerate(core.ACTION_DEFS):
            btn = QPushButton(name)
            btn.setToolTip(f"{action} — {tip}")
            if risk == "danger":
                btn.setProperty("danger", True)
            btn.clicked.connect(
                lambda _=False, a=action, k=extra_kind, r=risk, n=name: self._run_action(a, k, r, n)
            )
            grid.addWidget(btn, i // 3, i % 3)
            self.action_buttons.append(btn)
        v.addLayout(grid)
        v.addStretch(1)
        return w

    def _build_terminal_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(9)
        warn = QLabel("手动 Shell 是唯一的任意命令入口，输出原样返回。请确认你理解每一条命令再执行。")
        warn.setWordWrap(True)
        warn.setProperty("warn", True)
        v.addWidget(warn)

        row = QHBoxLayout()
        self.cmd_edit = QLineEdit()
        self.cmd_edit.setPlaceholderText("例如：id   /   pm list packages -3   /   dumpsys battery")
        self.cmd_edit.returnPressed.connect(self._run_terminal)
        row.addWidget(self.cmd_edit, 1)
        self.btn_cmd = QPushButton("执行")
        self.btn_cmd.setProperty("accent", True)
        self.btn_cmd.clicked.connect(self._run_terminal)
        row.addWidget(self.btn_cmd)
        v.addLayout(row)

        self.terminal_out = QPlainTextEdit()
        self.terminal_out.setReadOnly(True)
        self.terminal_out.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 9.5pt;")
        v.addWidget(self.terminal_out, 1)
        return w

    def _build_result_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(7)
        head = QHBoxLayout()
        self.result_summary = QLabel("尚无执行结果")
        head.addWidget(self.result_summary, 1)
        self.btn_raw = QPushButton("查看原始输出")
        self.btn_raw.setCheckable(True)
        self.btn_raw.toggled.connect(self._toggle_raw)
        head.addWidget(self.btn_raw)
        v.addLayout(head)

        self.result_stack = QStackedWidget()
        self.result_table = QTableWidget(0, 4)
        self.result_table.setHorizontalHeaderLabels(["分组", "条目", "结果", "详情"])
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.result_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.result_raw = QPlainTextEdit()
        self.result_raw.setReadOnly(True)
        self.result_raw.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 9pt;")
        self.result_stack.addWidget(self.result_table)
        self.result_stack.addWidget(self.result_raw)
        v.addWidget(self.result_stack, 1)
        return w

    def _build_log_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 10, 12, 10)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 9pt;")
        v.addWidget(self.log_view)
        b = QPushButton("清空日志")
        b.clicked.connect(self.log_view.clear)
        v.addWidget(b, 0, Qt.AlignRight)
        return w

    # ------------------------------------------------------------- 基础设施

    def log(self, msg: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"{stamp}  {msg}")

    def _busy(self, value: bool, text: str = ""):
        for b in (self.btn_refresh_dev, self.btn_refresh_apps, self.btn_grant,
                  self.btn_revoke, self.btn_cmd, self.btn_resolve_label):
            b.setEnabled(not value)
        for b in self.action_buttons:
            b.setEnabled(not value)
        if text:
            self.status_label.setText(text)

    def _async(self, fn: Callable, on_done: Callable | None = None,
               on_error: Callable | None = None, busy: str = "执行中…"):
        worker = Worker(fn)
        self.workers.append(worker)
        self._busy(True, busy)

        def cleanup():
            try:
                self.workers.remove(worker)
            except ValueError:
                pass
            self._busy(False)
            worker.deleteLater()
            if not any(x.isRunning() for x in self.workers) and self.serial:
                self.status_label.setText(f"就绪  ·  {self.serial}")

        def ok(value):
            cleanup()
            if on_done:
                on_done(value)

        def fail(message):
            cleanup()
            if on_error:
                on_error(message)
            else:
                self._error(message)

        worker.done.connect(ok)
        worker.failed.connect(fail)
        worker.start()

    def _error(self, msg: str):
        self.log(f"[错误] {msg}")
        self.status_label.setText(msg)
        QMessageBox.warning(self, "执行失败", msg)

    def _show_disclaimer(self):
        QMessageBox.information(
            self, "使用前请阅读",
            "本工具通过 adb shell 直接修改 Android 设备的应用状态与权限配置，属于高风险操作。\n\n"
            "· 只在自己的设备上使用，明确知道每个按钮的含义\n"
            "· 卸载第三方应用是真删，恢复只对预装应用有效\n"
            "· 不同 ROM 对冻结、隐藏、挂起的支持不一致\n"
            "· 由此造成的数据丢失、应用异常或系统不稳定由使用者自行承担\n\n"
            "原项目 GPL-3.0 © 2026 Yukstarlight；本 PC 版为其 fork 后的移植。",
        )
        self.settings.setValue("greeted", True)

    def _init_adb(self):
        try:
            self.adb = Adb(path=self.setting_adb_path() or None)
        except AdbError as e:
            self.log(f"[警告] {e}")
            self.status_label.setText("未找到 adb.exe —— 请到「设置」里指定路径")
            return
        self.log(f"adb: {self.adb.path}")
        self.identity_label.setText(self.adb.version())
        self.labels = LabelResolver(self.adb, self.setting_aapt2_path() or None)
        self.refresh_devices()

    def _open_settings(self):
        dlg = SettingsDialog(self, self.setting_adb_path(), self.setting_aapt2_path())
        if not dlg.exec():
            return
        adb_path, aapt2_path, confirm, autoswitch = dlg.values()
        self.settings.setValue("adb_path", adb_path)
        self.settings.setValue("aapt2_path", aapt2_path)
        self.settings.setValue("confirm_danger", confirm)
        self.settings.setValue("autoswitch", autoswitch)
        try:
            self.adb = Adb(path=adb_path or None)
            self.labels = LabelResolver(self.adb, aapt2_path or None)
            self.log(f"adb 已切换：{self.adb.path}")
            self.identity_label.setText(self.adb.version())
            self.refresh_devices()
        except AdbError as e:
            self._error(str(e))

    # ------------------------------------------------------------- 设备

    def refresh_devices(self):
        if not self.adb:
            return self._error("adb 未就绪，请先在「设置」里指定 adb.exe")
        self._async(
            lambda: self.adb.devices(),
            self._fill_devices,
            busy="正在枚举设备…",
        )

    def _fill_devices(self, devices: list[Device]):
        self.devices = devices
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        usable = [d for d in devices if d.usable]
        for d in usable:
            self.device_combo.addItem(d.label(), d.serial)
        if not usable:
            self.device_combo.addItem("（没有已授权的设备）", "")
        self.device_combo.blockSignals(False)
        states = ", ".join(f"{d.serial}:{d.state}" for d in devices) or "无"
        self.log(f"设备枚举：{states}")
        if usable:
            self.serial = usable[0].serial
            self.device_combo.setCurrentIndex(0)
            self._check_identity()
            self.refresh_apps()
        else:
            self.serial = ""
            self.status_label.setText("未连接设备 —— 请插上 USB 并允许 USB 调试")
            self.identity_label.setText("")

    def _on_device_changed(self, index: int):
        if index < 0 or not self.device_combo.count():
            return
        s = self.device_combo.itemData(index)
        if not s or s == self.serial:
            return
        self.serial = s
        self.log(f"切换设备：{s}")
        self._check_identity()
        self.refresh_apps()

    def _check_identity(self):
        if not self.serial:
            return
        as_root = self.root_box.isChecked()
        self._async(
            lambda: self.adb.shell_identity(self.serial, as_root=as_root),
            lambda v: (
                self.identity_label.setText(v[:110]),
                self.log(f"通道身份：{v.strip()}"),
            ),
            busy="正在检查 shell 身份…",
        )

    def _wifi_connect(self):
        if not self.adb:
            return
        text, ok = QInputDialog.getText(
            self, "WiFi ADB 连接", "手机 IP:端口（需先 USB 执行过 adb tcpip 5555）：",
            text="192.168.3.",
        )
        if not ok or not text.strip():
            return
        addr = text.strip()
        host, _, port = addr.rpartition(":")
        if not host:
            host, port = addr, "5555"
        self._async(
            lambda: self.adb.raw(["connect", f"{host}:{port}"], timeout=20),
            lambda r: (self.log(f"connect {host}:{port} → {r.text().strip()}"),
                       self.refresh_devices()),
            busy=f"正在连接 {host}:{port}…",
        )

    # ------------------------------------------------------------- 应用列表

    def refresh_apps(self):
        if not self.adb or not self.serial:
            return
        serial = self.serial
        self._async(
            lambda: (core.package_inventory(self.adb, serial),
                     core.dangerous_permissions(self.adb, serial)),
            self._fill_inventory,
            busy="正在读取应用列表…",
        )

    def _fill_inventory(self, data):
        inv, dangerous = data
        self.inventory = inv
        self.dangerous = dangerous
        third, system, disabled, uninstalled = (
            inv["third"], inv["system"], inv["disabled"], inv["uninstalled"]
        )
        installed = inv["installed"]
        apps: list[tuple[str, str, str, str]] = []
        for pkg in sorted(installed):
            kind = "系统" if pkg in system and pkg not in third else "第三方"
            state = "已冻结" if pkg in disabled else "正常"
            # label 初始留空，只有用户主动解析过才填中文名，避免和包名列重复
            apps.append((pkg, "", kind, state))
        for pkg in sorted(uninstalled):
            apps.append((pkg, "", "预装", "已卸载"))
        self.apps = apps
        self._fill_app_table()
        self.log(f"应用列表：已安装 {len(installed)} / 冻结 {len(disabled)} / "
                f"已卸载 {len(uninstalled)} / dangerous 权限 {len(dangerous)}")

    def _fill_app_table(self, *_):
        keyword = self.search_edit.text().strip().lower()
        mode = self.filter_combo.currentText()
        rows = []
        for pkg, label, kind, state in self.apps:
            if keyword and keyword not in pkg.lower() and keyword not in label.lower():
                continue
            if mode == "第三方" and kind != "第三方":
                continue
            if mode == "系统" and kind != "系统":
                continue
            if mode == "已冻结" and state != "已冻结":
                continue
            if mode == "已卸载" and state != "已卸载":
                continue
            rows.append((pkg, label, kind, state))

        self.app_table.blockSignals(True)
        self.app_table.setRowCount(len(rows))
        for i, (pkg, label, kind, state) in enumerate(rows):
            cells = (label or "—", pkg, kind, state)
            for j, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if j == 0 and not label:
                    item.setForeground(QColor("#a8adb8"))
                if j == 3 and state != "正常":
                    item.setForeground(QColor("#c5221f" if state == "已冻结" else "#b06000"))
                self.app_table.setItem(i, j, item)
        self.app_table.blockSignals(False)
        self.app_count.setText(f"显示 {len(rows)} / 共 {len(self.apps)} 个应用"
                               "  ·  中文名可点「解析当前应用名」按需加载")

    def _current_pkg(self) -> str:
        row = self.app_table.currentRow()
        if row < 0 or row >= self.app_table.rowCount():
            return ""
        item = self.app_table.item(row, 1)
        return item.text() if item else ""

    def _on_app_selected(self, *_):
        pkg = self._current_pkg()
        if not pkg:
            return
        self.grant_target.setText(pkg)
        self.action_target.setText(f"当前应用：{pkg}")
        self._load_target(pkg)

    def _reload_target(self):
        pkg = self._current_pkg()
        if pkg:
            self._load_target(pkg)

    def _load_target(self, pkg: str):
        if not self.adb or not self.serial:
            return
        self._async(
            lambda: core.describe(self.adb, self.serial, pkg),
            lambda t: self._fill_target(t),
            busy=f"正在读取 {pkg} 的清单…",
        )

    def _fill_target(self, t: core.Target):
        self.target = t
        self.perm_list.clear()
        suggested = core.suggested_permissions(t.perms, self.dangerous)
        for p in t.perms:
            item = QListWidgetItem(p)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if p in suggested else Qt.Unchecked)
            self.perm_list.addItem(item)
        self.acc_edit.setText(", ".join(t.accessibility))
        self.nl_edit.setText(", ".join(t.listeners))
        self.admin_edit.setText(", ".join(t.admins))
        self.grant_target.setText(f"{t.pkg}  ·  {len(t.perms)} 项权限 / "
                                  f"{len(t.accessibility)} 无障碍 / "
                                  f"{len(t.listeners)} 通知 / {len(t.admins)} 管理员")
        self.log(f"清单：{t.pkg} 权限={len(t.perms)} acc={len(t.accessibility)} "
                f"nl={len(t.listeners)} admin={len(t.admins)}")

    def _resolve_current_label(self):
        pkg = self._current_pkg()
        if not pkg or not self.labels:
            return
        if not self.labels.available:
            QMessageBox.information(self, "未找到 aapt2",
                                    "没有检测到 aapt2，应用名解析不可用。\n"
                                    "功能不受影响，列表会显示包名。可在「设置」里手动指定 aapt2.exe。")
            return
        self._async(
            lambda: self.labels.resolve(self.serial, pkg),
            lambda name: self._apply_label(pkg, name),
            busy=f"正在解析 {pkg} 的应用名…",
        )

    def _apply_label(self, pkg: str, name: str):
        if not name:
            self.log(f"{pkg}: 未能解析应用名")
            return
        self.apps = [(p, name if p == pkg else l, k, s) for p, l, k, s in self.apps]
        self._fill_app_table()
        self.grant_target.setText(f"{name}  ({pkg})")
        self.log(f"应用名：{pkg} → {name}")

    def _check_all(self, checked: bool):
        for i in range(self.perm_list.count()):
            self.perm_list.item(i).setCheckState(Qt.Checked if checked else Qt.Unchecked)

    # ------------------------------------------------------------- 执行

    def _require_device(self) -> bool:
        if not self.adb or not self.serial:
            QMessageBox.information(self, "没有设备", "请先连接并授权一台 Android 设备。")
            return False
        return True

    def _split_components(self, text: str) -> list[str]:
        out = []
        for part in (text or "").replace("，", ",").split(","):
            part = part.strip()
            if not part:
                continue
            norm = core.normalize_component(self.target.pkg if self.target else "", part)
            if not norm:
                raise ValueError(f"非法组件名：{part}")
            out.append(norm)
        return out

    def _current_target(self) -> core.Target:
        perms = []
        for i in range(self.perm_list.count()):
            item = self.perm_list.item(i)
            if item.checkState() == Qt.Checked:
                perms.append(item.text())
        t = core.Target(pkg=self.target.pkg if self.target else "")
        t.perms = perms
        t.accessibility = self._split_components(self.acc_edit.text())
        t.listeners = self._split_components(self.nl_edit.text())
        t.admins = self._split_components(self.admin_edit.text())
        return t

    def _confirm_danger(self, name: str, detail: str) -> bool:
        if not self.setting_confirm():
            return True
        return QMessageBox.question(
            self, "确认高风险操作",
            f"即将执行「{name}」。\n\n{detail}\n\n确定继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) == QMessageBox.Yes

    def _run_grant(self, revoke: bool):
        if not self._require_device() or not self.target:
            return
        try:
            t = self._current_target()
            script = core.grant_script(t, revoke=revoke)
        except ValueError as e:
            return self._error(str(e))
        name = "一键撤销" if revoke else "一键授权"
        if revoke and not self._confirm_danger(name, "会撤销选中的运行时权限、AppOps、"
                                                      "无障碍、通知使用权与设备管理员。"):
            return
        self._execute_script(name, script, timeout=300)

    def _run_action(self, action: str, extra_kind: str | None, risk: str, name: str):
        if not self._require_device():
            return
        pkg = self._current_pkg()
        if not pkg:
            if action not in NO_PKG_ACTIONS:
                return QMessageBox.information(self, "未选择应用", "请先在左侧选择一个应用。")
            pkg = PLACEHOLDER_PKG

        extra = ""
        if extra_kind == "perm":
            default = ""
            if self.target and self.target.perms:
                default = self.target.perms[0]
            text, ok = QInputDialog.getText(self, name, "权限名（如 android.permission.CAMERA）：", text=default)
            if not ok:
                return
            extra = text.strip()
        elif extra_kind == "component":
            default = ""
            if self.target:
                default = {
                    "acc_on": self.target.accessibility, "acc_off": self.target.accessibility,
                    "nl_on": self.target.listeners, "nl_off": self.target.listeners,
                    "admin_on": self.target.admins, "admin_off": self.target.admins,
                }.get(action, [])
                default = default[0] if default else ""
            text, ok = QInputDialog.getText(
                self, name, "完整类名（如 com.foo.MyService，也接受 com.foo/.MyService）：",
                text=default,
            )
            if not ok:
                return
            extra = core.normalize_component(pkg, text.strip()) or text.strip()
        elif extra_kind == "appop":
            item, ok = QInputDialog.getItem(self, name, "选择 AppOp：", list(core.APPOPS), 0, False)
            if not ok:
                return
            extra = item

        try:
            script = core.op_script(action, pkg, extra)
        except ValueError as e:
            return self._error(f"参数校验失败：{e}")

        meta = next((d for d in core.ACTION_DEFS if d[0] == action), None)
        tip = meta[4] if meta else ""
        if risk == "danger" and not self._confirm_danger(name, tip):
            return
        self._execute_script(f"{name} · {pkg}", script, timeout=180)

    def _run_terminal(self):
        if not self._require_device():
            return
        cmd = self.cmd_edit.text().strip()
        if not cmd:
            return
        self.terminal_out.appendPlainText(f"$ {cmd}\n")
        self.cmd_edit.clear()
        as_root = self.root_box.isChecked()
        self._async(
            lambda: self.adb.shell(self.serial, cmd, timeout=120, as_root=as_root),
            lambda r: (self.terminal_out.appendPlainText(
                          (r.text() or "(无输出)") + "\n" + "-" * 60 + "\n"),
                       self.log(f"手动 shell: {cmd}")),
            busy="执行命令中…",
        )

    def _execute_script(self, name: str, script: str, timeout: int = 180):
        if not self._require_device():
            return
        serial, as_root = self.serial, self.root_box.isChecked()
        started = time.monotonic()

        def work():
            r = self.adb.exec_script(serial, script, timeout=timeout, as_root=as_root)
            return r, time.monotonic() - started

        self._async(work, lambda data: self._show_result(name, data[0], data[1]),
                    busy=f"正在执行：{name} …")

    def _show_result(self, name: str, result, elapsed: float):
        items = core.parse_receipt(result.out)
        self.result_raw.setPlainText(
            f"# {name}\n# exit={result.rc}  elapsed={elapsed:.2f}s\n\n"
            + (result.out or "(无 stdout)") + ("\n[stderr]\n" + result.err if result.err.strip() else "")
        )
        counts = {"ok": 0, "skip": 0, "fail": 0}
        for r in items:
            counts[r.state] = counts.get(r.state, 0) + 1
        self.result_summary.setText(
            f"{name}  ·  成功 {counts['ok']} / 跳过 {counts['skip']} / 失败 {counts['fail']}"
            f"  ·  耗时 {elapsed:.2f}s  ·  exit={result.rc}"
        )
        self.result_table.setRowCount(len(items))
        for i, r in enumerate(items):
            cells = (r.group_name, r.key, STATE_TEXT.get(r.state, r.state), r.detail)
            for j, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if j == 2 and r.state in STATE_COLORS:
                    it.setBackground(STATE_COLORS[r.state])
                self.result_table.setItem(i, j, it)
        self.log(f"{name} → ok={counts['ok']} skip={counts['skip']} "
                 f"fail={counts['fail']} ({elapsed:.2f}s)")
        if not items and result.err.strip():
            self.log(f"[stderr] {result.err.strip()[:300]}")
        if self.setting_autoswitch():
            self.bottom_tabs.setCurrentIndex(0)
            self.btn_raw.setChecked(False)

    def _toggle_raw(self, checked: bool):
        self.result_stack.setCurrentIndex(1 if checked else 0)
