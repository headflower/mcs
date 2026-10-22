"""插件文件系统：全盘可读，写入限定在游戏目录与启动器数据目录。"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from .paths import data_root, plugin_data_dir


class FileAccessError(PermissionError):
    pass


class SafeFileSystem:
    def __init__(self, settings: Any) -> None:
        self._settings = settings

    @property
    def game_dir(self) -> Path:
        return self._settings.game_dir.resolve()

    @property
    def data_dir(self) -> Path:
        return data_root().resolve()

    def _resolve_read(self, path: str | Path) -> Path:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self.game_dir / p
        return p.resolve()

    def _resolve_write(self, path: str | Path) -> Path:
        p = self._resolve_read(path)
        if not self._is_writable(p):
            raise FileAccessError(
                f"出于安全考虑，插件只能写入游戏目录或启动器数据目录：{p}\n"
                f"允许的根目录：{self.game_dir} / {self.data_dir}"
            )
        return p

    def _is_writable(self, path: Path) -> bool:
        norm = os.path.normcase(os.path.abspath(str(path)))
        for root in (self.game_dir, self.data_dir):
            root_norm = os.path.normcase(os.path.abspath(str(root)))
            try:
                if os.path.commonpath([norm, root_norm]) == root_norm:
                    return True
            except ValueError:
                continue
        return False

    # ------------------------------------------------------------------- read
    def read_bytes(self, path: str | Path) -> bytes:
        return self._resolve_read(path).read_bytes()

    def read_text(
        self, path: str | Path, encoding: str = "utf-8", errors: str = "strict"
    ) -> str:
        return self._resolve_read(path).read_text(encoding=encoding, errors=errors)

    def read_json(self, path: str | Path) -> Any:
        return json.loads(self.read_text(path))

    def exists(self, path: str | Path) -> bool:
        try:
            return self._resolve_read(path).exists()
        except OSError:
            return False

    def list_dir(self, path: str | Path) -> list[Path]:
        p = self._resolve_read(path)
        if not p.is_dir():
            return []
        return sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))

    def stat(self, path: str | Path) -> os.stat_result:
        return self._resolve_read(path).stat()

    # ------------------------------------------------------------------ write
    def write_bytes(self, path: str | Path, data: bytes) -> Path:
        p = self._resolve_write(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".mcs-tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)
        return p

    def write_text(self, path: str | Path, text: str, encoding: str = "utf-8") -> Path:
        return self.write_bytes(path, text.encode(encoding))

    def write_json(self, path: str | Path, obj: Any) -> Path:
        return self.write_text(path, json.dumps(obj, ensure_ascii=False, indent=2))

    def ensure_dir(self, path: str | Path) -> Path:
        p = self._resolve_write(path)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def delete(self, path: str | Path, recursive: bool = False) -> None:
        p = self._resolve_write(path)
        if not p.exists():
            return
        if p.is_dir():
            if not recursive:
                raise IsADirectoryError(f"目录需要 recursive=True：{p}")
            shutil.rmtree(p)
        else:
            p.unlink()

    def copy(self, src: str | Path, dest: str | Path) -> Path:
        src_p = self._resolve_read(src)
        dest_p = self._resolve_write(dest)
        dest_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_p, dest_p)
        return dest_p

    def plugin_data(self, plugin_id: str) -> Path:
        p = plugin_data_dir(plugin_id)
        p.mkdir(parents=True, exist_ok=True)
        return p
