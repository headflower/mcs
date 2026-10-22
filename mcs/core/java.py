"""Java 运行时发现与版本解析。

核心只负责“找到 Java”。下载 Java 是官方插件 java_manager 的职责，
它把运行时安装到 data/java/ 下，这里的扫描会自动发现。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..api.types import JavaRuntimeInfo
from .paths import java_dir

log = logging.getLogger("mcs.java")


def _parse_release(path: Path) -> tuple[str, str, str]:
    version = implementor = arch = ""
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith('JAVA_VERSION="'):
                version = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith('IMPLEMENTOR="'):
                implementor = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith('OS_ARCH="'):
                arch = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return version, implementor, arch


def _major_from_version(version: str) -> int:
    if not version:
        return 0
    if version.startswith("1."):
        parts = version.split(".")
        return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    match = re.match(r"(\d+)", version)
    return int(match.group(1)) if match else 0


def java_executable(home: Path) -> Path | None:
    name = "java.exe" if sys.platform == "win32" else "java"
    candidates = [home / "bin" / name] if home.is_dir() else []
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def inspect_java(exe: Path, managed: bool = False) -> JavaRuntimeInfo | None:
    exe = exe.resolve()
    home = exe.parent.parent
    version, implementor, arch = _parse_release(home / "release")
    if not version:
        try:
            output = subprocess.run(
                [str(exe), "-version"], capture_output=True, text=True, timeout=10,
                creationflags=0x08000000 if sys.platform == "win32" else 0,
            ).stderr
            match = re.search(r'version "([^"]+)"', output)
            if match:
                version = match.group(1)
            match = re.search(r"(?:Runtime Environment|VM) \((.*?)\)", output)
            if match:
                implementor = implementor or match.group(1)
        except Exception:
            return None
    major = _major_from_version(version)
    if not major:
        return None
    return JavaRuntimeInfo(
        path=str(exe),
        version=version,
        major=major,
        vendor=implementor,
        arch=arch or ("x86_64" if sys.maxsize > 2**32 else "x86"),
        managed=managed,
    )


def _registry_java_homes() -> Iterable[Path]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []
    homes: list[Path] = []
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\JavaSoft\JDK"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\JavaSoft\JRE"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\JavaSoft\Java Development Kit"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\JavaSoft\Java Runtime Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Eclipse Adoptium\JDK"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Eclipse Adoptium\JRE"),
    ]
    access = getattr(winreg, "KEY_WOW64_64KEY", 0) | getattr(winreg, "KEY_READ", 0)
    for hive, subkey in roots:
        try:
            with winreg.OpenKey(hive, subkey, 0, access) as key:
                index = 0
                while True:
                    try:
                        name = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(key, name) as version_key:
                            java_home, _ = winreg.QueryValueEx(version_key, "JavaHome")
                            if java_home:
                                homes.append(Path(java_home))
                    except OSError:
                        continue
        except OSError:
            continue
    return homes


def _common_java_homes() -> Iterable[Path]:
    if sys.platform != "win32":
        return []
    bases = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
    ]
    patterns = ["Java/*", "Eclipse Adoptium/*", "Microsoft/jdk*", "Zulu/*", "BellSoft/*", "Amazon Corretto/*"]
    for base in bases:
        if not base.is_dir():
            continue
        for pattern in patterns:
            try:
                yield from base.glob(pattern)
            except OSError:
                continue


class JavaRegistry:
    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._cache: list[JavaRuntimeInfo] = []
        self._scanned = False

    @property
    def managed_dir(self) -> Path:
        return java_dir()

    def _managed_executables(self) -> Iterable[Path]:
        root = self.managed_dir
        if not root.is_dir():
            return []
        name = "java.exe" if sys.platform == "win32" else "java"
        seen: set[Path] = set()
        results: list[Path] = []
        for pattern in ("*/bin/" + name, "*/*/bin/" + name):
            for exe in root.glob(pattern):
                if exe not in seen:
                    seen.add(exe)
                    results.append(exe)
        return results

    def scan(self, force: bool = False) -> list[JavaRuntimeInfo]:
        if self._scanned and not force:
            return list(self._cache)
        found: dict[str, JavaRuntimeInfo] = {}

        def add(exe: Path | None, managed: bool) -> None:
            if not exe:
                return
            key = os.path.normcase(str(exe))
            if key in found:
                return
            info = inspect_java(exe, managed=managed)
            if info:
                found[key] = info

        preferred = str(self._settings.get("java_path") or "")
        if preferred:
            p = Path(preferred)
            add(java_executable(p) if p.is_dir() else p, False)

        for env_name in ("MCS_JAVA_HOME", "JAVA_HOME"):
            value = os.environ.get(env_name)
            if value:
                add(java_executable(Path(value)), False)

        for exe in self._managed_executables():
            add(exe, True)
        for home in list(_registry_java_homes()) + list(_common_java_homes()):
            add(java_executable(home), False)

        which = shutil.which("java")
        if which:
            add(Path(which), False)

        runtimes = sorted(found.values(), key=lambda r: (r.managed, r.major, r.version), reverse=True)
        self._cache = runtimes
        self._scanned = True
        return list(runtimes)

    def get(self, exe_path: str) -> JavaRuntimeInfo | None:
        if not exe_path:
            return None
        p = Path(exe_path)
        exe = java_executable(p) if p.is_dir() else p
        if exe and exe.is_file():
            return inspect_java(exe, managed=str(exe).lower().startswith(str(self.managed_dir).lower()))
        return None

    def find(self, required_major: int = 8, preferred: str = "") -> JavaRuntimeInfo | None:
        if preferred:
            info = self.get(preferred)
            if info and (not required_major or info.major >= required_major):
                return info
        runtimes = self.scan()
        exact = [r for r in runtimes if r.major == required_major]
        if exact:
            return exact[0]
        newer = sorted((r for r in runtimes if r.major > required_major), key=lambda r: r.major)
        if newer:
            return newer[0]
        return None
