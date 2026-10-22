"""账户凭据的本地加密存储。

Windows 使用 DPAPI（当前用户绑定），其它平台退化为权限 600 的明文文件，
并明确记录在文件头里。目标只是避免令牌以明文躺在磁盘上。
"""

from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_MAGIC_DPAPI = b"MCS-DPAPI-1\n"
_MAGIC_PLAIN = b"MCS-PLAIN-1\n"


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _dpapi(data: bytes, protect: bool) -> bytes:
    in_blob = _blob(data)
    out_blob = _DATA_BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if protect:
        ok = fn(ctypes.byref(in_blob), "MCS Launcher", None, None, None, 0, ctypes.byref(out_blob))
    else:
        ok = fn(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob))
    if not ok:
        raise OSError(ctypes.get_last_error(), "DPAPI 调用失败")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def protect(data: bytes) -> bytes:
    if sys.platform == "win32":
        return _dpapi(data, True)
    return data


def unprotect(data: bytes) -> bytes:
    if sys.platform == "win32":
        return _dpapi(data, False)
    return data


def read_secure_json(path: Path, default: Any) -> Any:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return default
    try:
        if raw.startswith(_MAGIC_DPAPI):
            payload = unprotect(base64.b64decode(raw[len(_MAGIC_DPAPI):]))
        elif raw.startswith(_MAGIC_PLAIN):
            payload = base64.b64decode(raw[len(_MAGIC_PLAIN):])
        else:
            payload = raw
        return json.loads(payload.decode("utf-8"))
    except Exception:
        log.exception("无法解密账户数据：%s", path)
        return default


def write_secure_json(path: Path, obj: Any) -> None:
    payload = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
    try:
        if sys.platform == "win32":
            blob = protect(payload)
            raw = _MAGIC_DPAPI + base64.b64encode(blob)
        else:
            raw = _MAGIC_PLAIN + base64.b64encode(payload)
    except Exception:
        log.exception("DPAPI 加密失败，账户数据将以明文形式保存")
        raw = _MAGIC_PLAIN + base64.b64encode(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(raw)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
