"""构建 MCS Launcher 的 Windows 独立 exe 与发布压缩包。

用法（Windows）：
    .\\.venv\\Scripts\\python.exe tools\\build_release.py
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
RELEASE_ROOT = ROOT / "release"
ASSETS = ROOT / "assets"
VERSION = "1.0.2"
APP_NAME = "MCSLauncher"
ZIP_NAME = f"MCSLauncher-{VERSION}-win64.zip"

EXCLUDE_DIRS = {"__pycache__", ".venv", ".idea", "build", "dist", "release"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".dll", ".lib", ".pdb", ".exp", ".so"}
SOURCE_ITEMS = [
    "main.py",
    "README.md",
    "requirements.txt",
    ".gitignore",
    "mcs",
    "sdk",
    "tests",
    "tools",
    "assets",
    "docs",
]


def run(args: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(args))
    completed = subprocess.run(args, cwd=cwd, env=env)
    if completed.returncode != 0:
        raise SystemExit(f"命令失败（退出码 {completed.returncode}）：{' '.join(args)}")


def write_version_file(path: Path) -> None:
    path.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=(1,0,0,0), prodvers=(1,0,0,0), mask=0x3f, flags=0x0,
    OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'MCS'),
        StringStruct('FileDescription', 'MCS Launcher'),
        StringStruct('FileVersion', '{VERSION}'),
        StringStruct('InternalName', '{APP_NAME}'),
        StringStruct('OriginalFilename', '{APP_NAME}.exe'),
        StringStruct('ProductName', 'MCS Launcher'),
        StringStruct('ProductVersion', '{VERSION}'),
        StringStruct('LegalCopyright', 'MCS Launcher contributors')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )


def build_exe() -> Path:
    try:
        import PyInstaller  # noqa: F401
        import PIL  # noqa: F401
    except ImportError as exc:
        raise SystemExit("缺少打包依赖，请先执行：pip install pyinstaller pillow") from exc

    icon = ASSETS / "mcs.ico"
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
    run([sys.executable, str(ROOT / "tools" / "make_icon.py")], env=env)

    version_file = BUILD / "version_info.txt"
    BUILD.mkdir(parents=True, exist_ok=True)
    write_version_file(version_file)

    data_arg = f"{ROOT / 'mcs' / 'official'}{os.pathsep}mcs/official"
    runtime_dir = DIST / APP_NAME
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    legacy_exe = DIST / f"{APP_NAME}.exe"
    if legacy_exe.exists():
        legacy_exe.unlink()
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--contents-directory",
            "_internal",
            "--windowed",
            "--name",
            APP_NAME,
            "--icon",
            str(icon),
            "--version-file",
            str(version_file),
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD / "pyinstaller"),
            "--specpath",
            str(BUILD),
            "--add-data",
            data_arg,
            "--exclude-module",
            "tkinter",
            str(ROOT / "main.py"),
        ],
        env=env,
    )
    exe = runtime_dir / f"{APP_NAME}.exe"
    if not exe.exists():
        raise SystemExit(f"PyInstaller 没有生成 {exe}")
    print(f"exe: {exe} ({exe.stat().st_size / 1024 / 1024:.1f} MiB)")
    return exe


def copy_source_tree(source: Path, target: Path) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored = {name for name in names if name in EXCLUDE_DIRS}
        ignored |= {name for name in names if Path(name).suffix.lower() in EXCLUDE_SUFFIXES}
        return ignored

    shutil.copytree(source, target, ignore=ignore, dirs_exist_ok=True)


def make_release(exe: Path) -> tuple[Path, Path]:
    folder = RELEASE_ROOT / f"MCSLauncher-{VERSION}-win64"
    if folder.exists():
        shutil.rmtree(folder)
    # onedir：可执行文件必须与 _internal 目录放在一起。
    shutil.copytree(exe.parent, folder)
    for item in SOURCE_ITEMS:
        source = ROOT / item
        target = folder / item
        if source.is_dir():
            copy_source_tree(source, target)
        else:
            shutil.copy2(source, target)

    zip_path = RELEASE_ROOT / ZIP_NAME
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(folder.parent).as_posix())
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    checksum = zip_path.with_suffix(zip_path.suffix + ".sha256")
    checksum.write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    print(f"release: {zip_path} ({zip_path.stat().st_size / 1024 / 1024:.1f} MiB)")
    print(f"sha256: {digest}")
    return zip_path, checksum


def main() -> None:
    exe = build_exe()
    make_release(exe)
    print("完成。")


if __name__ == "__main__":
    main()
