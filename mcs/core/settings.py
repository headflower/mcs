"""基于 JSON 的设置存储，线程安全，支持变更通知。"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from .paths import data_root, default_game_dir

log = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "game_dir": str(default_game_dir()),
    "java_path": "",
    "memory_mb": 4096,
    "jvm_args": "-XX:+UseG1GC -XX:+UnlockExperimentalVMOptions -XX:G1NewSizePercent=20",
    "game_args": "",
    "fullscreen": False,
    "microsoft_client_id": "4a07b708-b86d-4365-a55f-f4f23ecb85ab",
    "download_mirror": "official",  # official | bmclapi
    "curseforge_api_key": "",
    "show_console": True,
    "close_on_launch": False,
    "last_page": "home",
    "last_version": "",
    "last_account": "",
    "accent": "#7C5CFF",
    "disabled_plugins": [],
    "window_geometry": "",
}


class Settings(QObject):
    changed = pyqtSignal(str, object)

    def __init__(self, path: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = path or (data_root() / "settings.json")
        self._lock = threading.RLock()
        self._data: dict[str, Any] = dict(DEFAULTS)
        self._load()

    # ------------------------------------------------------------------ io
    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data.update({k: v for k, v in raw.items() if k in DEFAULTS})
        except FileNotFoundError:
            pass
        except Exception:
            log.exception("读取设置失败：%s", self._path)
        if not self.get("game_dir"):
            self._data["game_dir"] = str(default_game_dir())
        # 旧版内置的公共客户端 ID 已被微软停用，静默迁移到当前默认值。
        legacy_ids = {"00000000402b5328", ""}
        if str(self._data.get("microsoft_client_id") or "").strip() in legacy_ids:
            self._data["microsoft_client_id"] = DEFAULTS["microsoft_client_id"]
            self.save()

    def save(self) -> None:
        with self._lock:
            payload = json.dumps(self._data, ensure_ascii=False, indent=2)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception:
            log.exception("保存设置失败：%s", self._path)

    # --------------------------------------------------------------- access
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any, *, save: bool = True) -> None:
        with self._lock:
            if self._data.get(key) == value:
                return
            self._data[key] = value
        if save:
            self.save()
        self.changed.emit(key, value)

    def update(self, values: dict[str, Any], *, save: bool = True) -> None:
        changed: list[tuple[str, Any]] = []
        with self._lock:
            for key, value in values.items():
                if self._data.get(key) != value:
                    self._data[key] = value
                    changed.append((key, value))
        if save and changed:
            self.save()
        for key, value in changed:
            self.changed.emit(key, value)

    def all(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)

    def reset(self, key: str) -> None:
        self.set(key, DEFAULTS.get(key))

    # ------------------------------------------------------------- helpers
    @property
    def game_dir(self) -> Path:
        return Path(str(self.get("game_dir") or default_game_dir())).expanduser()

    @property
    def memory_mb(self) -> int:
        try:
            return max(512, int(self.get("memory_mb") or 4096))
        except (TypeError, ValueError):
            return 4096
