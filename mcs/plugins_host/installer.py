"""插件 ZIP 安装器：安全解包、校验清单并放入用户插件目录。"""

from __future__ import annotations

import logging
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

from ..api.types import PluginMeta
from ..core.paths import plugins_dir
from .manifest import ManifestError, load_manifest

log = logging.getLogger("mcs.plugins.install")

MAX_ENTRIES = 20000
MAX_UNCOMPRESSED = 256 * 1024 * 1024


class PluginInstallError(RuntimeError):
    pass


def _safe_member(name: str) -> str:
    normalized = name.replace("\\", "/").lstrip("/")
    parts = normalized.split("/")
    if not normalized or any(part in ("", ".", "..") for part in parts):
        raise PluginInstallError(f"压缩包包含非法路径：{name}")
    if re.match(r"^[A-Za-z]:", normalized):
        raise PluginInstallError(f"压缩包包含绝对路径：{name}")
    return "/".join(parts)


def _member_prefix(names: list[str]) -> str:
    if "plugin.json" in names:
        return ""
    manifests = [name[: -len("plugin.json")] for name in names if name.endswith("/plugin.json")]
    if len(manifests) != 1:
        raise PluginInstallError("压缩包根目录或唯一子目录中必须包含 plugin.json")
    return manifests[0]


def _install_dir_name(meta: PluginMeta) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", meta.id).strip(".-") or "plugin"
    return base[:80]


def install_zip(
    archive_path: str | Path,
    *,
    overwrite: bool = False,
    target_root: Path | None = None,
) -> PluginMeta:
    """安装插件 ZIP，返回已写入的插件清单。

    支持 plugin.json 位于压缩包根目录，或位于唯一顶层目录。拒绝路径穿越、
    符号链接以及过大的压缩包。
    """
    archive_path = Path(archive_path)
    if not archive_path.is_file():
        raise PluginInstallError(f"找不到插件压缩包：{archive_path}")
    root = target_root or plugins_dir()
    root.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            if len(infos) > MAX_ENTRIES:
                raise PluginInstallError("压缩包文件数量过多，已拒绝安装。")
            total = sum(info.file_size for info in infos)
            if total > MAX_UNCOMPRESSED:
                raise PluginInstallError("压缩包解压后超过 256 MB，已拒绝安装。")
            for info in infos:
                if info.external_attr and stat.S_ISLNK(info.external_attr >> 16):
                    raise PluginInstallError(f"压缩包包含符号链接：{info.filename}")
            names = [_safe_member(info.filename) for info in infos]
            prefix = _member_prefix(names)
            with tempfile.TemporaryDirectory(prefix=".mcs-install-", dir=root) as temp:
                staging = Path(temp)
                for info, name in zip(infos, names):
                    if prefix and not name.startswith(prefix):
                        continue
                    relative = name[len(prefix) :]
                    if not relative:
                        continue
                    destination = (staging / relative).resolve()
                    if staging.resolve() not in destination.parents:
                        raise PluginInstallError(f"压缩包路径越界：{info.filename}")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, destination.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)

                try:
                    meta = load_manifest(staging, builtin=False)
                except ManifestError as exc:
                    raise PluginInstallError(f"插件清单无效：{exc}") from exc
                entry = (staging / meta.entry).resolve()
                if staging.resolve() not in entry.parents or not entry.is_file():
                    raise PluginInstallError(f"插件入口不存在：{meta.entry}")

                target = root / _install_dir_name(meta)
                if target.exists():
                    if not overwrite:
                        raise PluginInstallError(f"插件目录已存在：{target.name}。请先移除旧版本或选择覆盖。")
                    shutil.rmtree(target)
                staging.rename(target)
                meta.path = str(target)
                log.info("已安装插件：%s %s -> %s", meta.id, meta.version, target)
                return meta
    except zipfile.BadZipFile as exc:
        raise PluginInstallError("不是有效的 ZIP 压缩包。") from exc


def uninstall_plugin(meta: PluginMeta, *, plugin_root: Path | None = None) -> None:
    """删除用户插件目录；内置插件不允许删除。"""
    if meta.builtin:
        raise PluginInstallError("内置插件不能移除，只能禁用。")
    root = (plugin_root or plugins_dir()).resolve()
    path = Path(meta.path).resolve()
    if path.parent != root:
        raise PluginInstallError(f"拒绝删除插件目录之外的路径：{path}")
    if path.exists():
        shutil.rmtree(path)
    log.info("已移除插件：%s", meta.id)
