"""轻量后台任务：插件用它在工作线程里下载/安装，并安全地回到 UI 线程。"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from ..api.types import TaskCancelled

log = logging.getLogger("mcs.tasks")


class TaskHandle:
    def __init__(self, title: str = "", dispatch: Callable[[Callable[[], Any]], None] | None = None) -> None:
        self.title = title
        self._cancel = threading.Event()
        self._done = threading.Event()
        self._muted = False
        self._dispatch = dispatch or (lambda fn: fn())
        self.on_progress: Callable[[int, int, str], None] | None = None
        self.on_status: Callable[[str], None] | None = None

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def done(self) -> bool:
        return self._done.is_set()

    @property
    def muted(self) -> bool:
        return self._muted

    def cancel(self) -> None:
        self._cancel.set()

    def mute(self) -> None:
        """取消任务并丢弃之后排队的所有回调（插件卸载时使用）。"""
        self._muted = True
        self._cancel.set()

    def check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise TaskCancelled()

    def progress(self, done: int, total: int, message: str = "") -> None:
        callback = self.on_progress
        if callback and not self._muted:
            self._dispatch(lambda: callback(done, total, message) if not self._muted else None)

    def status(self, message: str) -> None:
        callback = self.on_status
        if callback and not self._muted:
            self._dispatch(lambda: callback(message) if not self._muted else None)

    def sleep(self, seconds: float) -> None:
        if self._cancel.wait(seconds):
            raise TaskCancelled()


class TaskRunner:
    def __init__(self, dispatch: Callable[[Callable[[], Any]], None] | None = None) -> None:
        self._dispatch = dispatch or (lambda fn: fn())
        self._threads: list[threading.Thread] = []

    def set_dispatch(self, dispatch: Callable[[Callable[[], Any]], None]) -> None:
        self._dispatch = dispatch

    def run(
        self,
        fn: Callable[[TaskHandle], Any],
        *,
        title: str = "",
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        on_cancelled: Callable[[], None] | None = None,
    ) -> TaskHandle:
        handle = TaskHandle(title, self._dispatch)
        handle.on_progress = on_progress
        handle.on_status = on_status

        def deliver(callback: Callable[[Any], None] | None, value: Any) -> None:
            if callback is None:
                return

            def call() -> None:
                if not handle.muted:
                    callback(value)

            self._dispatch(call)

        def worker() -> None:
            try:
                try:
                    result = fn(handle)
                except TaskCancelled:
                    deliver(on_cancelled, None) if on_cancelled else None
                except BaseException as exc:  # noqa: BLE001
                    log.exception("后台任务失败：%s", title or fn)
                    deliver(on_error, exc)
                else:
                    deliver(on_done, result)
            finally:
                handle._done.set()

        thread = threading.Thread(target=worker, name=f"mcs-task-{title or 'task'}", daemon=True)
        self._threads = [t for t in self._threads if t.is_alive()]
        self._threads.append(thread)
        thread.start()
        return handle
