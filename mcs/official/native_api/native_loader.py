"""原生（C / C++）插件加载器。

插件通过稳定 C ABI 与启动器通信：

* 导出 ``const MCSPluginV1* mcs_plugin_entry(void)``；
* ``on_load`` 收到 :class:`MCSHostApi` 函数表指针，可注册钩子、读写文件、访问网络；
* ``on_unload`` 用于释放资源。

函数表的头文件位于 ``sdk/native/mcs_plugin.h``。该模块本身是一个普通 Python
插件，因此未安装或禁用本插件时，原生插件会得到明确的“未找到加载器”提示。
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable

from mcs.api.types import PluginMeta

log = logging.getLogger("mcs.native")

MCS_NATIVE_ABI = 1
MAX_STRING_BUFFERS = 256

LOG_LEVELS = {0: logging.DEBUG, 1: logging.INFO, 2: logging.WARNING, 3: logging.ERROR}

MCSHookCallback = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p)
MCSLogFn = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p)
MCSRegisterHookFn = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.c_char_p, MCSHookCallback, ctypes.c_void_p
)
MCSGetStringFn = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)
MCSNoArgStringFn = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)
MCSWriteFileFn = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p
)
MCSEmitFn = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p)


class MCSHostApi(ctypes.Structure):
    _fields_ = [
        ("abi_version", ctypes.c_uint32),
        ("host", ctypes.c_void_p),
        ("log", MCSLogFn),
        ("register_hook", MCSRegisterHookFn),
        ("get_setting", MCSGetStringFn),
        ("plugin_data_dir", MCSNoArgStringFn),
        ("game_dir", MCSNoArgStringFn),
        ("read_text_file", MCSGetStringFn),
        ("write_text_file", MCSWriteFileFn),
        ("http_get", MCSGetStringFn),
        ("emit_hook", MCSEmitFn),
        ("last_error", MCSNoArgStringFn),
    ]


class MCSPluginV1(ctypes.Structure):
    pass


MCSPluginOnLoad = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.POINTER(MCSHostApi), ctypes.POINTER(ctypes.c_void_p)
)
MCSPluginOnUnload = ctypes.CFUNCTYPE(None, ctypes.c_void_p)

MCSPluginV1._fields_ = [
    ("abi_version", ctypes.c_uint32),
    ("id", ctypes.c_char_p),
    ("name", ctypes.c_char_p),
    ("version", ctypes.c_char_p),
    ("on_load", MCSPluginOnLoad),
    ("on_unload", MCSPluginOnUnload),
]


def _decode(value: bytes | None) -> str:
    if not value:
        return ""
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode("utf-8", "replace")


def _json_safe(value: Any, depth: int = 0) -> Any:
    """把任意 Python 对象转换成可 JSON 序列化的结构。"""
    if depth > 4:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v, depth + 1) for v in value]
    if hasattr(value, "public_dict") and callable(value.public_dict):
        return _json_safe(value.public_dict(), depth + 1)
    if is_dataclass(value):
        return _json_safe(asdict(value), depth + 1)
    return str(value)


class HostBridge:
    """一条原生插件与启动器之间的函数表。"""

    def __init__(self, context: Any, plugin_id: str) -> None:
        self.ctx = context
        self.plugin_id = plugin_id
        self._closed = False
        self._buffers: list[Any] = []
        self._hook_callbacks: list[Any] = []
        self._last_error = ""
        self._api = MCSHostApi(
            abi_version=MCS_NATIVE_ABI,
            host=None,
            log=MCSLogFn(self._log),
            register_hook=MCSRegisterHookFn(self._register_hook),
            get_setting=MCSGetStringFn(self._get_setting),
            plugin_data_dir=MCSNoArgStringFn(self._plugin_data_dir),
            game_dir=MCSNoArgStringFn(self._game_dir),
            read_text_file=MCSGetStringFn(self._read_text_file),
            write_text_file=MCSWriteFileFn(self._write_text_file),
            http_get=MCSGetStringFn(self._http_get),
            emit_hook=MCSEmitFn(self._emit_hook),
            last_error=MCSNoArgStringFn(self._last_error_fn),
        )

    # ------------------------------------------------------------- helpers
    def _check(self) -> None:
        if self._closed:
            raise RuntimeError("原生插件已卸载")

    def _string(self, text: str | None) -> int:
        """返回一个在插件生命周期内有效的 UTF-8 指针地址。

        不能直接让 ctypes 回调返回 ``c_char_p``：ctypes 会警告内存泄漏，
        而且缓冲区可能提前被回收。这里把缓冲区保存在 ``_buffers`` 中，
        并向 C 返回它的地址。
        """
        data = (text or "").encode("utf-8")
        buffer = ctypes.create_string_buffer(data, len(data) + 1)
        self._buffers.append(buffer)
        if len(self._buffers) > MAX_STRING_BUFFERS:
            del self._buffers[: MAX_STRING_BUFFERS // 4]
        return ctypes.addressof(buffer)

    def _fail(self, message: str) -> None:
        self._last_error = message
        log.warning("原生插件 %s：%s", self.plugin_id, message)

    # ------------------------------------------------------------ callbacks
    def _log(self, _host: Any, level: int, message: bytes | None) -> None:
        try:
            self.ctx.logger.log(LOG_LEVELS.get(int(level), logging.INFO), _decode(message))
        except Exception:
            pass

    def _register_hook(
        self,
        _host: Any,
        hook: bytes | None,
        callback: Any,
        userdata: Any,
    ) -> int:
        try:
            self._check()
            name = _decode(hook)
            if not name or callback is None:
                self._fail("register_hook 参数不合法")
                return 0
            cb = callback

            def invoke(_user: Any, _hook: bytes | None, payload: bytes | None, *_: Any) -> None:
                try:
                    cb(userdata, hook, payload)
                except Exception:
                    log.exception("原生插件 %s 的钩子 %s 执行失败", self.plugin_id, name)

            wrapper = MCSHookCallback(invoke)
            self.ctx.host.hooks.register(name, self._make_hook(name, wrapper), plugin_id=self.plugin_id)
            self._hook_callbacks.append(wrapper)
            return 1
        except Exception as exc:
            self._fail(f"注册钩子失败：{exc}")
            return 0

    def _make_hook(self, name: str, wrapper: Any) -> Callable[..., None]:
        def hook(**kwargs: Any) -> None:
            try:
                payload = json.dumps(_json_safe(kwargs), ensure_ascii=False)
            except Exception:
                payload = "{}"
            try:
                wrapper(None, name.encode("utf-8"), payload.encode("utf-8"))
            except Exception:
                log.exception("调用原生钩子 %s 失败", name)

        return hook

    def _get_setting(self, _host: Any, key: bytes | None) -> int:
        try:
            self._check()
            value = self.ctx.settings.get(_decode(key))
            return self._string(json.dumps(_json_safe(value), ensure_ascii=False))
        except Exception as exc:
            self._fail(str(exc))
            return 0

    def _plugin_data_dir(self, _host: Any) -> int:
        try:
            self._check()
            return self._string(str(self.ctx.data_dir))
        except Exception as exc:
            self._fail(str(exc))
            return 0

    def _game_dir(self, _host: Any) -> int:
        try:
            self._check()
            return self._string(str(self.ctx.fs.game_dir))
        except Exception as exc:
            self._fail(str(exc))
            return 0

    def _read_text_file(self, _host: Any, path: bytes | None) -> int:
        try:
            self._check()
            text = self.ctx.fs.read_text(_decode(path), errors="replace")
            return self._string(text)
        except FileNotFoundError:
            return 0
        except Exception as exc:
            self._fail(str(exc))
            return 0

    def _write_text_file(self, _host: Any, path: bytes | None, text: bytes | None) -> int:
        try:
            self._check()
            self.ctx.fs.write_text(_decode(path), _decode(text))
            return 0
        except Exception as exc:
            self._fail(str(exc))
            return -1

    def _http_get(self, _host: Any, url: bytes | None) -> int:
        try:
            self._check()
            return self._string(self.ctx.http.get_text(_decode(url)))
        except Exception as exc:
            self._fail(str(exc))
            return 0

    def _emit_hook(self, _host: Any, name: bytes | None, payload: bytes | None) -> int:
        try:
            self._check()
            hook = _decode(name)
            data: Any = {}
            if payload:
                try:
                    data = json.loads(_decode(payload))
                except json.JSONDecodeError:
                    data = {}
            if not isinstance(data, dict):
                data = {"value": data}
            self.ctx.host.hooks.emit(hook, **data)
            return 0
        except Exception as exc:
            self._fail(str(exc))
            return -1

    def _last_error_fn(self, _host: Any) -> int:
        return self._string(self._last_error)

    @property
    def api(self) -> MCSHostApi:
        return self._api

    def close(self) -> None:
        self._closed = True
        self._hook_callbacks.clear()
        self._buffers.clear()


class NativePluginLoader:
    """``kind == "native"`` 的宿主侧包装。"""

    def __init__(self, meta: PluginMeta) -> None:
        self.meta = meta
        self.ctx: Any = None
        self._lib: Any = None
        self._plugin: Any = None
        self._state = ctypes.c_void_p()
        self._bridge: HostBridge | None = None
        self._has_state = False

    @property
    def plugin_path(self) -> Path:
        return Path(self.meta.path) / self.meta.entry

    def on_load(self, context: Any) -> None:
        self.ctx = context
        path = self.plugin_path
        if not path.is_file():
            raise RuntimeError(f"原生插件文件不存在：{path}")
        if os.name == "nt":
            try:
                os.add_dll_directory(str(path.parent))
            except (AttributeError, OSError):
                pass
        try:
            lib = ctypes.CDLL(str(path))
        except OSError as exc:
            raise RuntimeError(f"无法加载原生插件 {path.name}：{exc}") from exc
        try:
            entry = lib.mcs_plugin_entry
        except AttributeError as exc:
            raise RuntimeError(
                f"{path.name} 缺少导出函数 mcs_plugin_entry（请参考 sdk/native/mcs_plugin.h）"
            ) from exc
        entry.restype = ctypes.POINTER(MCSPluginV1)
        entry.argtypes = []
        plugin = entry().contents
        abi = int(plugin.abi_version)
        if abi < 1 or abi > MCS_NATIVE_ABI:
            raise RuntimeError(
                f"原生插件 ABI {abi} 不受支持（启动器支持 1..{MCS_NATIVE_ABI}）"
            )
        plugin_id = _decode(plugin.id)
        if plugin_id != self.meta.id:
            raise RuntimeError(
                f"原生插件 id 不匹配：plugin.json 为 {self.meta.id}，二进制为 {plugin_id or '空'}"
            )
        if not plugin.on_load:
            raise RuntimeError("原生插件没有提供 on_load")
        self._lib = lib
        self._plugin = plugin
        self._bridge = HostBridge(context, self.meta.id)
        result = plugin.on_load(ctypes.byref(self._bridge.api), ctypes.byref(self._state))
        if result != 0:
            raise RuntimeError(f"原生插件 on_load 返回错误码 {result}")
        self._has_state = True
        context.logger.info(
            "原生插件已加载：%s %s（ABI %s）",
            _decode(plugin.name) or self.meta.name,
            _decode(plugin.version) or self.meta.version,
            abi,
        )

    def on_unload(self) -> None:
        try:
            if self._plugin is not None and self._plugin.on_unload:
                self._plugin.on_unload(self._state)
        except Exception:
            log.exception("卸载原生插件失败：%s", self.meta.id)
        finally:
            self._has_state = False
            if self._bridge is not None:
                self._bridge.close()
                self._bridge = None
            self._plugin = None
            self._lib = None
