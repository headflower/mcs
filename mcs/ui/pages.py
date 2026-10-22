"""核心页面：主页、版本、账户、设置。"""

from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..api.types import LaunchOptions
from ..core.launcher import LaunchError
from ..core.paths import data_root, logs_dir, plugins_dir
from .widgets import Avatar, Card, Divider, SectionHeader, Toast

log = logging.getLogger("mcs.ui.pages")


def _muted(text: str, *, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(wrap)
    return label


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Hint")
    label.setWordWrap(True)
    return label


def _ghost(text: str, slot: Callable[[], None] | None = None) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("Ghost")
    if slot is not None:
        button.clicked.connect(slot)
    return button


def _link(text: str, slot: Callable[[], None]) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("Link")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(slot)
    return button


class HomePage(QWidget):
    def __init__(self, host: Any, window: Any) -> None:
        super().__init__()
        self.host = host
        self.window = window
        self.settings = host.settings
        self.accounts = host.accounts
        self.launcher = host.launcher
        self._build()
        self.launcher.versions_changed.connect(self.refresh_versions)
        self.launcher.state_changed.connect(self._on_state)
        self.launcher.launch_started.connect(self._on_started)
        self.launcher.launch_finished.connect(self._on_finished)
        self.launcher.log_line.connect(self._append_log)
        self.launcher.error.connect(lambda text: self.window.show_toast("启动失败", text, "error"))
        self.accounts.current_changed.connect(lambda _acc: self.refresh_account())
        self.accounts.accounts_changed.connect(self.refresh_account)
        self.settings.changed.connect(self._on_setting)
        self.refresh_versions()
        self.refresh_account()

    # ----------------------------------------------------------------- ui
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        hero = Card(accent=True)
        hero.body.setContentsMargins(26, 24, 26, 24)
        hero.body.setSpacing(16)

        top = QHBoxLayout()
        top.setSpacing(16)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        eyebrow = QLabel("MINECRAFT: JAVA EDITION")
        eyebrow.setObjectName("Hint")
        title = QLabel("开始新的冒险")
        title.setObjectName("PageTitle")
        subtitle = QLabel("选择版本，点击启动。所有下载与扩展功能都由插件提供。")
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        titles.addWidget(eyebrow)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        top.addLayout(titles, 1)

        account_box = QVBoxLayout()
        account_box.setSpacing(8)
        account_box.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        account_row = QHBoxLayout()
        account_row.setSpacing(10)
        self.avatar = Avatar("?", 42)
        self.account_name = QLabel("未登录")
        self.account_name.setObjectName("SectionTitle")
        self.account_meta = QLabel("登录正版账户后即可启动")
        self.account_meta.setObjectName("Hint")
        names = QVBoxLayout()
        names.setSpacing(1)
        names.addWidget(self.account_name)
        names.addWidget(self.account_meta)
        account_row.addWidget(self.avatar)
        account_row.addLayout(names)
        account_box.addLayout(account_row)
        self.account_button = _ghost("切换账户", lambda: self.window.open_login_dialog())
        account_box.addWidget(self.account_button, alignment=Qt.AlignmentFlag.AlignRight)
        top.addLayout(account_box)
        hero.body.addLayout(top)

        version_row = QHBoxLayout()
        version_row.setSpacing(10)
        self.version_combo = QComboBox()
        self.version_combo.setMinimumWidth(320)
        self.version_combo.currentIndexChanged.connect(self._remember_version)
        version_row.addWidget(self.version_combo, 1)
        refresh = _ghost("刷新", self._refresh_clicked)
        refresh.setToolTip("重新扫描 versions 目录")
        version_row.addWidget(refresh)
        version_row.addWidget(_link("管理版本 →", lambda: self.window.show_page("versions")))
        hero.body.addLayout(version_row)

        launch_row = QHBoxLayout()
        launch_row.setSpacing(12)
        self.launch_button = QPushButton("启动游戏")
        self.launch_button.setObjectName("Primary")
        self.launch_button.setMinimumWidth(180)
        self.launch_button.setMinimumHeight(46)
        self.launch_button.clicked.connect(self._launch)
        launch_row.addWidget(self.launch_button)

        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName("Danger")
        self.stop_button.setMinimumHeight(46)
        self.stop_button.hide()
        self.stop_button.clicked.connect(self._stop)
        launch_row.addWidget(self.stop_button)

        self.launch_hint = QLabel("")
        self.launch_hint.setObjectName("Hint")
        self.launch_hint.setWordWrap(True)
        launch_row.addWidget(self.launch_hint, 1)
        hero.body.addLayout(launch_row)
        layout.addWidget(hero)

        bottom = QHBoxLayout()
        bottom.setSpacing(16)

        log_card = Card()
        log_head = QHBoxLayout()
        log_head.addWidget(SectionHeader("运行日志", "启动器与游戏进程的实时输出"))
        log_head.addStretch(1)
        clear = _link("清空", self._clear_log)
        log_head.addWidget(clear)
        log_card.body.addLayout(log_head)
        self.console = QPlainTextEdit()
        self.console.setObjectName("Console")
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(1200)
        self.console.setMinimumHeight(170)
        self.console.setPlaceholderText("等待启动…")
        log_card.body.addWidget(self.console, 1)
        bottom.addWidget(log_card, 3)

        quick = Card()
        quick.body.addWidget(SectionHeader("快捷操作"))
        self.version_count = _muted("正在扫描本地版本…")
        quick.body.addWidget(self.version_count)
        quick.body.addWidget(Divider())
        for text, slot in (
            ("打开游戏目录", lambda: self.host.ui.open_path(self.settings.game_dir)),
            ("版本管理", lambda: self.window.show_page("versions")),
            ("账户管理", lambda: self.window.show_page("account")),
            ("打开日志目录", lambda: self.host.ui.open_path(logs_dir())),
            ("启动器设置", lambda: self.window.show_page("settings")),
        ):
            button = _ghost(text, slot)
            button.setMinimumHeight(36)
            quick.body.addWidget(button)
        quick.body.addStretch(1)
        bottom.addWidget(quick, 1)
        layout.addLayout(bottom, 1)
        self._append_log(f"[MCS] MCS Launcher {__version__} 已就绪")

    # ------------------------------------------------------------- actions
    def refresh_versions(self) -> None:
        versions = self.launcher.versions()
        previous = self.version_combo.currentData() or self.settings.get("last_version", "")
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        if versions:
            for version in versions:
                label = version.name
                if version.loader and version.loader != "vanilla":
                    label += f"  ·  {version.loader}"
                self.version_combo.addItem(label, version.id)
            index = self.version_combo.findData(previous)
            self.version_combo.setCurrentIndex(index if index >= 0 else 0)
            self.version_count.setText(f"已安装 {len(versions)} 个版本")
            self.launch_button.setEnabled(not self.launcher.running)
            self.launch_hint.setText("")
        else:
            self.version_combo.addItem("尚未安装任何版本", None)
            self.version_count.setText("本地还没有可启动的版本")
            self.launch_button.setEnabled(False)
            self.launch_hint.setText("请先在「游戏下载」插件中安装一个版本，然后回到这里启动。")
        self.version_combo.blockSignals(False)

    def refresh_account(self) -> None:
        account = self.accounts.current
        if account is None:
            self.avatar.set_name("?")
            self.account_name.setText("未登录")
            self.account_meta.setText("登录正版账户后即可启动")
            self.account_button.setText("登录账户")
            return
        self.avatar.set_name(account.name)
        self.account_name.setText(account.name)
        suffix = "登录已过期，请重新登录" if account.expired else "Microsoft 正版账户"
        self.account_meta.setText(suffix)
        self.account_button.setText("切换账户")

    def _remember_version(self, _index: int) -> None:
        version_id = self.version_combo.currentData()
        if version_id:
            self.settings.set("last_version", version_id, save=False)

    def _refresh_clicked(self) -> None:
        self.launcher.refresh_versions()
        self.window.show_toast("版本列表", "已重新扫描本地版本。")

    def _launch(self) -> None:
        version_id = self.version_combo.currentData()
        if not version_id:
            self.window.show_toast("无法启动", "请先安装一个游戏版本。", "warning")
            return
        if self.accounts.current is None:
            self.window.show_toast("需要登录", "启动游戏前请先登录 Microsoft 正版账户。", "warning")
            self.window.open_login_dialog()
            return
        options = LaunchOptions(
            memory_mb=int(self.settings.get("memory_mb", 4096)),
            jvm_args=str(self.settings.get("jvm_args", "")),
            game_args=str(self.settings.get("game_args", "")),
            fullscreen=bool(self.settings.get("fullscreen", False)),
            java_path=str(self.settings.get("java_path", "")),
        )
        try:
            self.launcher.launch(version_id, options)
        except LaunchError as exc:
            log.error("启动失败：%s", exc)
            self.window.show_toast("启动失败", str(exc), "error")
            self.host.ui.show_error(
                "无法启动游戏",
                str(exc),
                traceback.format_exc(),
                hint="请检查版本文件、Java 与账户状态；也可以到「日志」页面查看完整输出。",
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("启动失败")
            self.window.show_toast("启动失败", str(exc), "error")
            self.host.ui.show_error(
                "启动时发生内部错误",
                f"{type(exc).__name__}: {exc}",
                traceback.format_exc(),
                hint="错误详情已写入日志文件，可在「日志」页面查看。",
            )

    def _stop(self) -> None:
        if self.window.ui_service.confirm("停止游戏", "确定要结束当前游戏进程吗？"):
            self.launcher.stop()

    def _on_state(self, running: bool) -> None:
        self.launch_button.setEnabled(not running and self.version_combo.currentData() is not None)
        self.launch_button.setText("游戏运行中…" if running else "启动游戏")
        self.stop_button.setVisible(running)
        if running:
            self.launch_hint.setText("游戏正在运行，输出会显示在下方日志中。")
            self.window.set_status("游戏运行中", "busy")
        else:
            self.launch_hint.setText("")

    def _on_started(self, pid: int) -> None:
        self._append_log(f"[MCS] 游戏已启动，PID {pid}")

    def _on_finished(self, code: int) -> None:
        self.window.set_status("就绪", "ok")
        if code == 0:
            self.window.show_toast("游戏已退出", "进程正常结束。")
        else:
            self.window.show_toast("游戏已退出", f"进程退出代码：{code}", "warning")

    def _on_setting(self, key: str, _value: Any) -> None:
        if key == "last_version":
            index = self.version_combo.findData(_value)
            if index >= 0 and index != self.version_combo.currentIndex():
                self.version_combo.blockSignals(True)
                self.version_combo.setCurrentIndex(index)
                self.version_combo.blockSignals(False)

    def _append_log(self, line: str) -> None:
        self.console.appendPlainText(line)

    def _clear_log(self) -> None:
        self.console.clear()


class VersionsPage(QWidget):
    def __init__(self, host: Any, window: Any) -> None:
        super().__init__()
        self.host = host
        self.window = window
        self.launcher = host.launcher
        self._build()
        self.launcher.versions_changed.connect(self.refresh)
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        card = Card()
        head = QHBoxLayout()
        head.addWidget(
            SectionHeader("本地版本", "扫描 .minecraft/versions 目录，缺失文件请在游戏下载插件中补全"),
            1,
        )
        head.addWidget(_ghost("刷新", self.refresh))
        head.addWidget(_ghost("打开 versions", lambda: self.host.ui.open_path(self.launcher.versions_dir)))
        card.body.addLayout(head)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["版本", "类型", "加载器", "Java"])
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, self.table.horizontalHeader().ResizeMode.Stretch)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(320)
        card.body.addWidget(self.table)

        self.empty = _muted("还没有安装任何版本。安装官方「游戏下载」插件后，就能在这里看到已安装的版本。", wrap=True)
        card.body.addWidget(self.empty)
        layout.addWidget(card, 1)

    def refresh(self) -> None:
        versions = self.launcher.versions(refresh=True)
        self.table.setRowCount(len(versions))
        for row, version in enumerate(versions):
            values = [version.name, version.type, version.loader, str(version.java_major or "—")]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, version.id)
                self.table.setItem(row, column, item)
        self.empty.setVisible(not versions)
        self.table.setVisible(bool(versions))
        if versions:
            self.table.resizeColumnsToContents()
            self.table.horizontalHeader().setSectionResizeMode(0, self.table.horizontalHeader().ResizeMode.Stretch)


class AccountPage(QWidget):
    def __init__(self, host: Any, window: Any) -> None:
        super().__init__()
        self.host = host
        self.window = window
        self.accounts = host.accounts
        self.settings = host.settings
        self._build()
        self.accounts.accounts_changed.connect(self.refresh)
        self.accounts.current_changed.connect(lambda _acc: self.refresh())
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        current = Card(accent=True)
        current.body.setContentsMargins(26, 24, 26, 24)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.avatar = Avatar("?", 56)
        row.addWidget(self.avatar)
        info = QVBoxLayout()
        info.setSpacing(3)
        self.current_name = QLabel("未登录")
        self.current_name.setObjectName("PageTitle")
        self.current_uuid = QLabel("登录 Microsoft 账户以开始游戏")
        self.current_uuid.setObjectName("Muted")
        self.current_badge = QLabel("未登录")
        self.current_badge.setObjectName("Pill")
        info.addWidget(self.current_name)
        info.addWidget(self.current_uuid)
        info.addWidget(self.current_badge, alignment=Qt.AlignmentFlag.AlignLeft)
        row.addLayout(info, 1)
        actions = QVBoxLayout()
        actions.setSpacing(8)
        self.login_button = QPushButton("登录 / 添加账户")
        self.login_button.setObjectName("Primary")
        self.login_button.clicked.connect(self.window.open_login_dialog)
        actions.addWidget(self.login_button)
        self.refresh_button = _ghost("刷新登录状态", self._refresh_token)
        actions.addWidget(self.refresh_button)
        row.addLayout(actions)
        current.body.addLayout(row)
        layout.addWidget(current)

        list_card = Card()
        list_card.body.addWidget(SectionHeader("已保存的账户", "令牌使用 Windows DPAPI 加密保存在本机，不会上传到任何服务器"))
        self.rows = QVBoxLayout()
        self.rows.setSpacing(8)
        list_card.body.addLayout(self.rows)
        self.empty = _muted("还没有账户。点击右上角「登录 / 添加账户」开始。", wrap=True)
        list_card.body.addWidget(self.empty)
        layout.addWidget(list_card)

        about = Card()
        about.body.addWidget(SectionHeader("正版登录说明"))
        about.body.addWidget(
            _muted(
                "登录使用微软官方设备码流程，启动器不会看到你的密码。"
                "如果提示 XErr 2148916233，说明该微软账户还没有创建 Xbox 档案；"
                "XErr 2148916235 表示所在地区不支持 Xbox 服务。",
                wrap=True,
            )
        )
        layout.addWidget(about)
        layout.addStretch(1)

    def refresh(self) -> None:
        current = self.accounts.current
        if current:
            self.avatar.set_name(current.name)
            self.current_name.setText(current.name)
            self.current_uuid.setText(current.uuid or "—")
            self.current_badge.setText("登录已过期" if current.expired else "Microsoft 正版")
            self.current_badge.setObjectName("PillBusy" if current.expired else "PillOk")
        else:
            self.avatar.set_name("?")
            self.current_name.setText("未登录")
            self.current_uuid.setText("登录 Microsoft 账户以开始游戏")
            self.current_badge.setText("未登录")
            self.current_badge.setObjectName("Pill")
        self.current_badge.style().unpolish(self.current_badge)
        self.current_badge.style().polish(self.current_badge)

        while self.rows.count():
            item = self.rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        accounts = self.accounts.accounts
        self.empty.setVisible(not accounts)
        current_id = current.id if current else ""
        for account in accounts:
            frame = QFrame()
            frame.setObjectName("Card")
            line = QHBoxLayout(frame)
            line.setContentsMargins(14, 10, 14, 10)
            line.setSpacing(12)
            line.addWidget(Avatar(account.name, 34))
            text = QVBoxLayout()
            text.setSpacing(1)
            name = QLabel(account.name)
            name.setObjectName("SectionTitle")
            meta = QLabel(("当前账户 · " if account.id == current_id else "") + (account.uuid or "—"))
            meta.setObjectName("Hint")
            text.addWidget(name)
            text.addWidget(meta)
            line.addLayout(text, 1)
            if account.id != current_id:
                switch = _ghost("设为当前", lambda _=False, aid=account.id: self.accounts.set_current(aid))
                line.addWidget(switch)
            remove = QPushButton("移除")
            remove.setObjectName("Danger")
            remove.clicked.connect(lambda _=False, aid=account.id, n=account.name: self._remove(aid, n))
            line.addWidget(remove)
            self.rows.addWidget(frame)

    def _remove(self, account_id: str, name: str) -> None:
        if self.window.ui_service.confirm("移除账户", f"确定要移除账户「{name}」吗？需要重新登录才能恢复。"):
            self.accounts.remove(account_id)

    def _refresh_token(self) -> None:
        if self.accounts.current is None:
            self.window.show_toast("没有账户", "请先登录一个账户。", "warning")
            return
        client_id = str(self.settings.get("microsoft_client_id") or "").strip()

        def work(_task):
            return self.accounts.refresh_current(client_id)

        def done(account) -> None:
            self.window.show_toast("刷新成功", f"账户 {account.name} 的登录状态已更新。")

        def failed(exc: BaseException) -> None:
            self.window.show_toast("刷新失败", str(exc), "error")

        self.window.show_toast("正在刷新", "正在向微软刷新登录令牌…")
        self.host.tasks.run(work, title="刷新登录", on_done=done, on_error=failed)


def _section(title: str, subtitle: str = "") -> SectionHeader:
    return SectionHeader(title, subtitle)


def _field(title: str, widget: QWidget, hint: str = "") -> QWidget:
    wrapper = QWidget()
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    label = QLabel(title)
    label.setObjectName("Muted")
    layout.addWidget(label)
    layout.addWidget(widget)
    if hint:
        layout.addWidget(_hint(hint))
    return wrapper


class SettingsPage(QWidget):
    def __init__(self, host: Any, window: Any) -> None:
        super().__init__()
        self.host = host
        self.window = window
        self.settings = host.settings
        self._loading = True
        self._build()
        self._load_values()
        self._loading = False

    # ----------------------------------------------------------------- ui
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(16)

        # 游戏
        game = Card()
        game.body.addWidget(_section("游戏", "内存、窗口与启动参数"))
        self.game_dir = QLineEdit()
        browse = QPushButton("浏览…")
        browse.setObjectName("Ghost")
        browse.clicked.connect(self._browse_game_dir)
        open_dir = QPushButton("打开")
        open_dir.setObjectName("Ghost")
        open_dir.clicked.connect(lambda: self.host.ui.open_path(self.settings.game_dir))
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.game_dir, 1)
        dir_row.addWidget(browse)
        dir_row.addWidget(open_dir)
        dir_box = QWidget()
        dir_box.setLayout(dir_row)
        dir_row.setContentsMargins(0, 0, 0, 0)
        game.body.addWidget(_field("游戏目录", dir_box))
        self.game_dir.editingFinished.connect(self._save_game_dir)

        self.memory = QSlider(Qt.Orientation.Horizontal)
        self.memory.setRange(1024, 32768)
        self.memory.setSingleStep(512)
        self.memory.setPageStep(1024)
        self.memory_label = QLabel("4096 MB")
        self.memory_label.setObjectName("SectionTitle")
        mem_row = QHBoxLayout()
        mem_row.addWidget(self.memory, 1)
        mem_row.addWidget(self.memory_label)
        mem_box = QWidget()
        mem_box.setLayout(mem_row)
        mem_row.setContentsMargins(0, 0, 0, 0)
        game.body.addWidget(_field("最大内存", mem_box, "建议 4–8 GB；过大反而会拖慢游戏。"))
        self.memory.valueChanged.connect(self._on_memory)
        self.memory.sliderReleased.connect(self._save_memory)

        self.fullscreen = QCheckBox("以全屏启动")
        self.fullscreen.toggled.connect(lambda v: self.settings.set("fullscreen", v))
        game.body.addWidget(self.fullscreen)

        self.close_on_launch = QCheckBox("启动游戏后关闭启动器")
        self.close_on_launch.toggled.connect(lambda v: self.settings.set("close_on_launch", v))
        game.body.addWidget(self.close_on_launch)

        self.jvm_args = QLineEdit()
        self.jvm_args.setPlaceholderText("例如：-XX:+UseG1GC -XX:G1NewSizePercent=20")
        self.jvm_args.editingFinished.connect(
            lambda: self.settings.set("jvm_args", self.jvm_args.text().strip())
        )
        game.body.addWidget(_field("JVM 参数（可选）", self.jvm_args))

        self.game_args = QLineEdit()
        self.game_args.setPlaceholderText("例如：--width 1280 --height 720")
        self.game_args.editingFinished.connect(
            lambda: self.settings.set("game_args", self.game_args.text().strip())
        )
        game.body.addWidget(_field("游戏参数（可选）", self.game_args))
        layout.addWidget(game)

        # Java
        java = Card()
        java.body.addWidget(_section("Java 运行时", "启动器会自动寻找已安装的 Java；也可以让「Java 下载」插件自动安装"))
        self.java_combo = QComboBox()
        self.java_combo.currentIndexChanged.connect(self._save_java)
        rescan = _ghost("重新扫描", self._scan_java)
        java_row = QHBoxLayout()
        java_row.addWidget(self.java_combo, 1)
        java_row.addWidget(rescan)
        java_box = QWidget()
        java_box.setLayout(java_row)
        java_row.setContentsMargins(0, 0, 0, 0)
        java.body.addWidget(_field("使用的 Java", java_box))
        layout.addWidget(java)

        # 下载
        download = Card()
        download.body.addWidget(_section("下载", "官方源较慢时可以切换到 BMCLAPI 镜像"))
        self.mirror = QComboBox()
        self.mirror.addItem("Mojang 官方源", "official")
        self.mirror.addItem("BMCLAPI 镜像（国内加速）", "bmclapi")
        self.mirror.currentIndexChanged.connect(
            lambda _i: self.settings.set("download_mirror", self.mirror.currentData())
        )
        download.body.addWidget(_field("下载源", self.mirror))
        self.cf_key = QLineEdit()
        self.cf_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.cf_key.setPlaceholderText("CurseForge API Key（仅使用 CurseForge 渠道时需要）")
        self.cf_key.editingFinished.connect(
            lambda: self.settings.set("curseforge_api_key", self.cf_key.text().strip())
        )
        download.body.addWidget(_field("CurseForge API Key", self.cf_key))
        layout.addWidget(download)

        # 外观
        appearance = Card()
        appearance.body.addWidget(_section("外观", "强调色会立即应用到整个启动器"))
        self.accent = QComboBox()
        from .theme import ACCENTS

        for name, value in ACCENTS.items():
            self.accent.addItem(name, value)
        self.accent.currentIndexChanged.connect(self._apply_accent)

        self.accent_swatch = QLabel()
        self.accent_swatch.setFixedSize(28, 28)
        self.accent_swatch.setToolTip("当前强调色")
        custom = _ghost("自定义…", self._pick_accent)
        custom.setToolTip("从任意颜色中选择强调色")
        accent_row = QHBoxLayout()
        accent_row.setContentsMargins(0, 0, 0, 0)
        accent_row.setSpacing(8)
        accent_row.addWidget(self.accent, 1)
        accent_row.addWidget(self.accent_swatch)
        accent_row.addWidget(custom)
        accent_box = QWidget()
        accent_box.setLayout(accent_row)
        appearance.body.addWidget(
            _field("强调色", accent_box, "选择预设，或点「自定义…」使用任意颜色。")
        )
        self.client_id = QLineEdit()
        self.client_id.setPlaceholderText("默认使用内置 Azure 客户端 ID")
        self.client_id.editingFinished.connect(
            lambda: self.settings.set("microsoft_client_id", self.client_id.text().strip())
        )
        appearance.body.addWidget(
            _field("Microsoft 客户端 ID（高级）", self.client_id, "只有在你自行注册 Azure 应用时才需要修改。")
        )
        layout.addWidget(appearance)

        # 插件
        plugins = Card()
        head = QHBoxLayout()
        head.addWidget(_section("插件", "安装、启停与排查扩展，都在独立的插件管理页完成。"), 1)
        head.addWidget(_ghost("打开插件管理", lambda: self.window.show_page("plugins")))
        head.addWidget(_ghost("打开插件目录", lambda: self.host.ui.open_path(plugins_dir())))
        plugins.body.addLayout(head)
        plugins.body.addWidget(
            _muted("插件可以添加页面、挂钩启动流程；核心启动、设置与正版登录不依赖任何插件。", wrap=True)
        )
        layout.addWidget(plugins)

        # 关于
        about = Card()
        about.body.addWidget(_section("关于"))
        about.body.addWidget(_muted(f"MCS Launcher {__version__} · 插件 API v1", wrap=True))
        about.body.addWidget(
            _muted(
                "核心只负责启动、基础设置与正版登录。游戏下载、模组下载、Java 管理与原生插件接口都以官方插件形式提供。",
                wrap=True,
            )
        )
        layout.addWidget(about)
        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

    # ------------------------------------------------------------- loading
    def _load_values(self) -> None:
        s = self.settings
        self.game_dir.setText(str(s.game_dir))
        self.memory.setValue(int(s.get("memory_mb", 4096)))
        self.memory_label.setText(f"{self.memory.value()} MB")
        self.fullscreen.setChecked(bool(s.get("fullscreen", False)))
        self.close_on_launch.setChecked(bool(s.get("close_on_launch", False)))
        self.jvm_args.setText(str(s.get("jvm_args", "")))
        self.game_args.setText(str(s.get("game_args", "")))
        self.cf_key.setText(str(s.get("curseforge_api_key", "")))
        self.client_id.setText(str(s.get("microsoft_client_id", "")))
        self._select_data(self.mirror, s.get("download_mirror", "official"))
        from .theme import DEFAULT_ACCENT

        self._select_accent(str(s.get("accent", DEFAULT_ACCENT)))
        self._scan_java()

    @staticmethod
    def _select_data(combo: QComboBox, value: Any) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _select_accent(self, value: str) -> None:
        from .theme import ACCENTS, DEFAULT_ACCENT

        color = QColor(value)
        if not color.isValid():
            color = QColor(DEFAULT_ACCENT)
        value = color.name()
        index = self.accent.findData(value)
        if index < 0 and value not in ACCENTS.values():
            for row in range(self.accent.count() - 1, -1, -1):
                if self.accent.itemData(row) not in ACCENTS.values():
                    self.accent.removeItem(row)
            self.accent.addItem(f"自定义 · {value.upper()}", value)
            index = self.accent.count() - 1
        self.accent.blockSignals(True)
        if index >= 0:
            self.accent.setCurrentIndex(index)
        self.accent.blockSignals(False)
        self._sync_accent_swatch(value)

    def _sync_accent_swatch(self, value: str) -> None:
        self.accent_swatch.setStyleSheet(
            f"background: {value}; border: 1px solid rgba(255, 255, 255, 0.22); border-radius: 8px;"
        )
        self.accent_swatch.setToolTip(f"当前强调色：{value.upper()}")

    def _pick_accent(self) -> None:
        from .theme import DEFAULT_ACCENT

        start = QColor(str(self.accent.currentData() or DEFAULT_ACCENT))
        color = QColorDialog.getColor(start, self, "选择强调色")
        if not color.isValid():
            return
        self._select_accent(color.name())
        self._apply_accent(self.accent.currentIndex())

    def _save_game_dir(self) -> None:
        if self._loading:
            return
        text = self.game_dir.text().strip()
        if not text:
            self.game_dir.setText(str(self.settings.game_dir))
            return
        self.settings.set("game_dir", text)
        self.host.launcher.refresh_versions()
        self.window.show_toast("设置已保存", "游戏目录已更新。")

    def _on_memory(self, value: int) -> None:
        self.memory_label.setText(f"{value} MB")
        if not self._loading:
            self.settings.set("memory_mb", value, save=False)

    def _save_memory(self) -> None:
        self.settings.set("memory_mb", self.memory.value())

    def _save_java(self, _index: int) -> None:
        if self._loading:
            return
        self.settings.set("java_path", str(self.java_combo.currentData() or ""))

    def _scan_java(self) -> None:
        runtimes = self.host.launcher.java.scan(force=True)
        current = str(self.settings.get("java_path", "") or "")
        self.java_combo.blockSignals(True)
        self.java_combo.clear()
        self.java_combo.addItem("自动选择（推荐）", "")
        seen = set()
        for runtime in runtimes:
            if runtime.path in seen:
                continue
            seen.add(runtime.path)
            prefix = "托管 · " if runtime.managed else ""
            self.java_combo.addItem(prefix + runtime.label, runtime.path)
        if current:
            index = self.java_combo.findData(current)
            if index < 0:
                self.java_combo.addItem(f"手动指定 · {current}", current)
            else:
                index = self.java_combo.findData(current)
            self.java_combo.setCurrentIndex(index)
        self.java_combo.blockSignals(False)

    def _browse_game_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择游戏目录", str(self.settings.game_dir))
        if path:
            self.game_dir.setText(path)
            self._save_game_dir()

    def _apply_accent(self, _index: int) -> None:
        if self._loading:
            return
        color = str(self.accent.currentData() or "")
        if not QColor(color).isValid():
            color = "#7C5CFF"
        self.settings.set("accent", color)
        self._sync_accent_swatch(color)
        from PyQt6.QtWidgets import QApplication

        from .theme import apply_theme

        apply_theme(QApplication.instance(), color)
        self.window.refresh_icon()
