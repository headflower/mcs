"""Java 运行时下载与管理。"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any

ADOPTIUM_API = "https://api.adoptium.net/v3"
ADOPTIUM_ASSETS = ADOPTIUM_API + "/assets/latest/{major}/hotspot"
TUNA_ADOPTIUM = "https://mirrors.tuna.tsinghua.edu.cn/Adoptium"


class JavaInstallError(RuntimeError):
    pass


def _os_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def _arch_name() -> str:
    return "x64" if sys.maxsize > 2**32 else "x32"


def available_releases(ctx: Any) -> list[int]:
    try:
        data = ctx.http.get_json(f"{ADOPTIUM_API}/info/available_releases")
        values = [int(v) for v in data.get("available_releases") or []]
        if values:
            return sorted(set(values))
    except Exception:
        ctx.logger.exception("获取 Adoptium 版本列表失败")
    return [8, 11, 17, 21, 25]


def _package_for(ctx: Any, major: int) -> dict[str, Any]:
    params = {
        "architecture": _arch_name(),
        "image_type": "jre",
        "os": _os_name(),
        "vendor": "eclipse",
    }
    url = ADOPTIUM_ASSETS.format(major=major)
    data = ctx.http.get_json(url, **params)
    if not isinstance(data, list) or not data:
        raise JavaInstallError(f"Adoptium 没有为 Java {major} 提供可下载的运行时")
    binary = data[0].get("binary") or {}
    package = binary.get("package") or {}
    if not package.get("link"):
        raise JavaInstallError(f"Java {major} 的下载地址无效")
    return {
        "url": str(package["link"]),
        "name": str(package.get("name") or f"temurin-{major}.zip"),
        "size": int(package.get("size") or 0),
        "version": str((data[0].get("version") or {}).get("semver") or major),
    }


def _safe_extract(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            dest = (target / member.filename).resolve()
            if root not in dest.parents and dest != root:
                raise JavaInstallError("压缩包包含非法路径，已中止解压")
        zf.extractall(target)


def _find_java_home(root: Path) -> Path | None:
    name = "java.exe" if sys.platform == "win32" else "java"
    direct = root / "bin" / name
    if direct.is_file():
        return root
    for candidate in root.glob(f"*/bin/{name}"):
        return candidate.parent.parent
    for candidate in root.glob(f"*/*/bin/{name}"):
        return candidate.parent.parent
    return None


def install_runtime(ctx: Any, major: int, task: Any) -> Any:
    if sys.platform != "win32":
        # Adoptium 的其它平台使用 tar.gz；这里保留明确提示，避免静默装坏。
        raise JavaInstallError("当前版本的自动安装仅支持 Windows；请手动安装 Java 并在设置中选择。")
    task.status(f"正在查询 Java {major} 的最新版本…")
    package = _package_for(ctx, major)
    java_root = Path(ctx.java.managed_dir)
    java_root.mkdir(parents=True, exist_ok=True)
    final_dir = java_root / f"temurin-{major}-{package['version']}"
    if final_dir.is_dir() and _find_java_home(final_dir):
        ctx.java.scan(force=True)
        return ctx.java.find(major)

    with tempfile.TemporaryDirectory(prefix="mcs-java-") as temp:
        tempdir = Path(temp)
        archive = tempdir / "runtime.zip"
        task.status(f"正在下载 Temurin {major}…")
        primary = package["url"]
        mirror = (
            f"{TUNA_ADOPTIUM}/{major}/jre/{_arch_name()}/windows/"
            f"{package['name']}"
        )
        prefer_mirror = str(ctx.settings.get("download_mirror") or "") == "bmclapi"
        sources = [mirror, primary] if prefer_mirror else [primary, mirror]
        last_error: Exception | None = None
        for index, url in enumerate(sources):
            try:
                if index:
                    task.status(f"原下载源不可用，尝试备用源：{url.split('/')[2]}…")
                ctx.http.download(
                    url,
                    archive,
                    expected_size=package["size"] if url == primary else 0,
                    progress=lambda done, total, msg: task.progress(done, total, msg),
                    cancel=task.cancel_event,
                )
                last_error = None
                break
            except Exception as exc:  # 网络错误时尝试下一个源
                last_error = exc
                ctx.logger.warning("Java 下载源失败：%s（%s）", url, exc)
        if last_error is not None:
            raise JavaInstallError(f"Java {major} 下载失败：{last_error}") from last_error
        task.check_cancelled()
        extract_dir = tempdir / "extracted"
        task.status("正在解压 Java 运行时…")
        _safe_extract(archive, extract_dir)
        home = _find_java_home(extract_dir)
        if home is None:
            raise JavaInstallError("下载的 Java 压缩包中没有找到 java 可执行文件")
        if final_dir.exists():
            shutil.rmtree(final_dir, ignore_errors=True)
        shutil.move(str(home), str(final_dir))

    task.status("正在登记 Java 运行时…")
    ctx.java.scan(force=True)
    runtime = ctx.java.find(major)
    if runtime is None:
        raise JavaInstallError("Java 已解压，但未能识别其版本")
    return runtime


class JavaManager:
    """暴露给其它插件的服务：按需保证某个 Java 大版本存在。"""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._locks: dict[int, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock(self, major: int) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(major, threading.Lock())

    def ensure(self, major: int, task: Any) -> Any:
        runtime = self.ctx.java.find(major)
        if runtime is not None:
            return runtime
        with self._lock(major):
            runtime = self.ctx.java.find(major)
            if runtime is not None:
                return runtime
            return install_runtime(self.ctx, major, task)


def install_java(ctx: Any, major: int, task: Any) -> Any:
    return JavaManager(ctx).ensure(major, task)
