"""日志初始化：控制台 + 滚动文件 + 内存缓冲（供日志页面读取）。"""

from __future__ import annotations

import logging
import sys
import threading
from collections import deque
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable

LOG_FILE_NAME = "launcher.log"


@dataclass(frozen=True)
class LogEntry:
    created: float
    level: int
    level_name: str
    logger: str
    message: str

    def format(self) -> str:
        import time

        stamp = time.strftime("%H:%M:%S", time.localtime(self.created))
        return f"[{stamp}] {self.level_name:<7} {self.logger}: {self.message}"


class MemoryLogHandler(logging.Handler):
    """把最近的日志保留在内存里，UI 定时读取，不依赖 Qt 信号线程。"""

    def __init__(self, capacity: int = 5000) -> None:
        super().__init__(level=logging.DEBUG)
        self._entries: deque[tuple[int, LogEntry]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._sequence = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.exc_info:
                message += "\n" + logging.Formatter().formatException(record.exc_info)
            if record.stack_info:
                message += "\n" + logging.Formatter().formatStack(record.stack_info)
        except Exception:  # noqa: BLE001
            message = str(record.msg)
        entry = LogEntry(
            created=record.created,
            level=record.levelno,
            level_name=record.levelname,
            logger=record.name,
            message=message,
        )
        with self._lock:
            self._sequence += 1
            self._entries.append((self._sequence, entry))

    def entries(self, since: int = 0) -> tuple[list[LogEntry], int]:
        with self._lock:
            sequence = self._sequence
            snapshot = [entry for seq, entry in self._entries if seq > since]
        return snapshot, sequence

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()



_memory_handler: MemoryLogHandler | None = None


def memory_handler() -> MemoryLogHandler:
    global _memory_handler
    if _memory_handler is None:
        _memory_handler = MemoryLogHandler()
        _memory_handler.setFormatter(
            logging.Formatter("%(message)s")
        )
        if getattr(logging.getLogger(), "_mcs_configured", False):
            logging.getLogger().addHandler(_memory_handler)
    return _memory_handler


def log_path() -> Path:
    from .paths import logs_dir

    return Path(logs_dir()) / LOG_FILE_NAME


def read_log_tail(max_bytes: int = 256 * 1024) -> str:
    path = log_path()
    if not path.is_file():
        return ""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            data = handle.read()
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace")
    if size > max_bytes:
        newline = text.find("\n")
        if newline >= 0:
            text = text[newline + 1 :]
    return text


def setup_logging(level: int = logging.INFO) -> None:
    from .paths import logs_dir

    logs_dir().mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if getattr(root, "_mcs_configured", False):
        memory_handler()
        return
    root.setLevel(logging.DEBUG)
    file_format = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    short_format = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S")

    stream = sys.stderr or sys.stdout
    if stream is not None:
        console = logging.StreamHandler(stream)
        console.setFormatter(short_format)
        console.setLevel(level)
        root.addHandler(console)

    try:
        file_handler = RotatingFileHandler(
            log_path(), maxBytes=4 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(file_format)
        file_handler.setLevel(logging.DEBUG)
        root.addHandler(file_handler)
    except OSError:
        pass

    memory = memory_handler()
    memory.setLevel(logging.DEBUG)
    root.addHandler(memory)
    logging.captureWarnings(True)
    root._mcs_configured = True  # type: ignore[attr-defined]

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("PyQt6").setLevel(logging.WARNING)
