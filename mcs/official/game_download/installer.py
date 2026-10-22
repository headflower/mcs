"""Minecraft 原版与模组加载器安装逻辑。

这里刻意不依赖任何第三方启动库：只使用插件上下文提供的 HTTP / 文件系统能力，
并且在安装结束后让 LaunchService 重新扫描版本目录。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

from mcs.api.hooks import HOOK_GAME_VERSION_INSTALLED
from mcs.core.launcher import library_artifact, native_artifact, rules_allow

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
RESOURCES_URL = "https://resources.download.minecraft.net"
FORGE_MAVEN = "https://maven.minecraftforge.net"
NEOFORGE_MAVEN = "https://maven.neoforged.net/releases"
FABRIC_META = "https://meta.fabricmc.net"
QUILT_META = "https://meta.quiltmc.org"

FEATURES = {
    "is_demo_user": False,
    "has_custom_resolution": False,
    "has_quick_plays_support": False,
    "is_quick_play_singleplayer": False,
    "is_quick_play_multiplayer": False,
    "is_quick_play_realms": False,
}


class InstallError(RuntimeError):
    pass


# --------------------------------------------------------------------- 基础工具
def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def version_dir(ctx: Any, version_id: str) -> Path:
    return Path(ctx.launcher.game_dir) / "versions" / version_id


def is_installed(ctx: Any, version_id: str) -> bool:
    return (version_dir(ctx, version_id) / f"{version_id}.json").is_file()


def _emit_installed(ctx: Any, version_id: str) -> None:
    try:
        ctx.host.hooks.emit(HOOK_GAME_VERSION_INSTALLED, version_id=version_id)
    except Exception:  # 插件不应因为监听者异常而失败
        ctx.logger.exception("派发 game.version_installed 失败")
    try:
        ctx.launcher.refresh_versions()
    except Exception:
        ctx.logger.exception("刷新版本列表失败")


def _download_items(ctx: Any, items: list[dict[str, Any]], task: Any, label: str) -> None:
    from mcs.api.types import DownloadItem

    payload = []
    for item in items:
        url = str(item.get("url") or "")
        dest = Path(str(item.get("dest") or ""))
        if not url or not dest:
            continue
        payload.append(
            DownloadItem(
                url=url,
                dest=str(dest),
                sha1=str(item.get("sha1") or ""),
                size=int(item.get("size") or 0),
                label=str(item.get("label") or dest.name),
            )
        )
    if not payload:
        return
    task.status(label)
    ctx.http.download_many(
        payload,
        workers=8,
        progress=lambda done, total, msg: task.progress(done, total, msg),
        cancel=task.cancel_event,
    )
    task.check_cancelled()


def _ensure_java(ctx: Any, major: int, task: Any) -> str:
    """找到符合要求的 Java；没有就请求 Java 插件自动下载。"""
    runtime = ctx.java.find(major)
    if runtime is not None:
        return runtime.path
    service = ctx.services.get("java") or ctx.services.get("java.autodownload")
    if service is None:
        raise InstallError(
            f"安装这个版本需要 Java {major}，但本机没有找到。\n"
            "请在「Java 下载」插件中安装，或启用该插件后重试。"
        )
    task.status(f"本机没有 Java {major}，正在自动下载运行时…")
    runtime = service.ensure(major, task)
    if runtime is None:
        raise InstallError(f"Java {major} 自动下载失败，请在「Java 下载」插件中手动安装。")
    return runtime.path


# --------------------------------------------------------------------- 版本清单
def fetch_manifest(ctx: Any, *, force: bool = False) -> dict[str, Any]:
    cache = Path(ctx.data_dir) / "version_manifest_v2.json"
    if not force and cache.is_file():
        data = read_json(cache)
        if isinstance(data, dict) and data.get("versions"):
            return data
    data = ctx.http.get_json(MANIFEST_URL)
    if not isinstance(data, dict) or not data.get("versions"):
        raise InstallError("Mojang 版本清单格式异常")
    write_json(cache, data)
    return data


def fetch_version_json(ctx: Any, url: str) -> dict[str, Any]:
    data = ctx.http.get_json(url)
    if not isinstance(data, dict) or not data.get("id"):
        raise InstallError("版本 JSON 格式异常")
    return data


# --------------------------------------------------------------------- 原版安装
def install_vanilla(ctx: Any, version_id: str, task: Any) -> str:
    task.status(f"正在获取 {version_id} 的版本信息…")
    manifest = fetch_manifest(ctx)
    entry = next(
        (v for v in manifest["versions"] if str(v.get("id")) == version_id), None
    )
    if entry is None:
        raise InstallError(f"版本清单里没有 {version_id}")
    data = fetch_version_json(ctx, str(entry["url"]))
    data["id"] = version_id
    game_dir = Path(ctx.launcher.game_dir)
    vdir = version_dir(ctx, version_id)
    vdir.mkdir(parents=True, exist_ok=True)

    client = (data.get("downloads") or {}).get("client") or {}
    items: list[dict[str, Any]] = []
    if client.get("url"):
        items.append(
            {
                "url": client["url"],
                "dest": vdir / f"{version_id}.jar",
                "sha1": client.get("sha1", ""),
                "size": client.get("size", 0),
                "label": f"{version_id}.jar",
            }
        )

    libraries_dir = game_dir / "libraries"
    for lib in data.get("libraries") or []:
        if not isinstance(lib, dict):
            continue
        if not rules_allow(lib.get("rules"), FEATURES):
            continue
        art = library_artifact(lib)
        if art and art.get("url"):
            items.append(
                {
                    "url": art["url"],
                    "dest": libraries_dir / art["path"],
                    "sha1": art.get("sha1", ""),
                    "size": art.get("size", 0),
                    "label": Path(art["path"]).name,
                }
            )
        native = native_artifact(lib)
        if native and native.get("url"):
            items.append(
                {
                    "url": native["url"],
                    "dest": libraries_dir / native["path"],
                    "sha1": native.get("sha1", ""),
                    "size": native.get("size", 0),
                    "label": Path(native["path"]).name,
                }
            )

    asset_index = data.get("assetIndex") or {}
    index_id = str(asset_index.get("id") or data.get("assets") or "legacy")
    index_path = game_dir / "assets" / "indexes" / f"{index_id}.json"
    if asset_index.get("url"):
        items.append(
            {
                "url": asset_index["url"],
                "dest": index_path,
                "sha1": asset_index.get("sha1", ""),
                "size": asset_index.get("size", 0),
                "label": f"资源索引 {index_id}",
            }
        )
    logging_conf = (data.get("logging") or {}).get("client") or {}
    log_file = logging_conf.get("file") or {}
    log_target = None
    if log_file.get("url") and log_file.get("id"):
        log_target = game_dir / "assets" / "log_configs" / str(log_file["id"])
        items.append(
            {
                "url": log_file["url"],
                "dest": log_target,
                "sha1": log_file.get("sha1", ""),
                "size": log_file.get("size", 0),
                "label": str(log_file["id"]),
            }
        )

    _download_items(ctx, items, task, "正在下载游戏核心与依赖库…")

    if asset_index.get("url"):
        index = read_json(index_path)
        if not isinstance(index, dict):
            raise InstallError("资源索引下载失败")
        objects = index.get("objects") or {}
        task.status(f"正在准备 {len(objects)} 个游戏资源…")
        object_items = []
        for _name, obj in objects.items():
            if not isinstance(obj, dict):
                continue
            hash_value = str(obj.get("hash") or "")
            if len(hash_value) < 2:
                continue
            object_items.append(
                {
                    "url": f"{RESOURCES_URL}/{hash_value[:2]}/{hash_value}",
                    "dest": game_dir / "assets" / "objects" / hash_value[:2] / hash_value,
                    "sha1": hash_value,
                    "size": int(obj.get("size") or 0),
                    "label": hash_value[:8],
                }
            )
        _download_items(ctx, object_items, task, "正在下载游戏资源（首次安装会比较慢）…")

    java_version = data.get("javaVersion") or {}
    try:
        required_java = int(java_version.get("majorVersion") or 8)
    except (TypeError, ValueError):
        required_java = 8
    _ensure_java(ctx, required_java, task)
    # 最后才写版本 JSON：中途失败时不会留下一个“已安装但不完整”的条目。
    write_json(vdir / f"{version_id}.json", data)
    task.status(f"{version_id} 安装完成")
    _emit_installed(ctx, version_id)
    return version_id


def ensure_vanilla(ctx: Any, version_id: str, task: Any) -> None:
    if is_installed(ctx, version_id):
        return
    task.status(f"需要先安装原版 {version_id}，正在自动安装…")
    install_vanilla(ctx, version_id, task)


# --------------------------------------------------------------------- 加载器查询
def _maven_versions(ctx: Any, url: str) -> list[str]:
    text = ctx.http.get_text(url)
    versions = re.findall(r"<version>([^<]+)</version>", text)
    return [v.strip() for v in versions if v.strip()]


def forge_versions(ctx: Any, minecraft: str) -> list[str]:
    url = f"{FORGE_MAVEN}/net/minecraftforge/forge/maven-metadata.xml"
    result = []
    for value in _maven_versions(ctx, url):
        if value.startswith(minecraft + "-"):
            result.append(value[len(minecraft) + 1 :])
    return list(reversed(result))


def fabric_loader_versions(ctx: Any, minecraft: str) -> list[str]:
    data = ctx.http.get_json(f"{FABRIC_META}/v2/versions/loader/{quote(minecraft)}")
    result: list[str] = []
    for item in data:
        loader = item.get("loader") or {}
        value = loader.get("version") or item.get("version")
        if value:
            result.append(str(value))
    return result


def quilt_loader_versions(ctx: Any, minecraft: str) -> list[str]:
    data = ctx.http.get_json(f"{QUILT_META}/v3/versions/loader/{quote(minecraft)}")
    result = []
    for item in data:
        loader = item.get("loader") or {}
        if loader.get("version"):
            result.append(str(loader["version"]))
    return result


def neoforge_versions(ctx: Any, minecraft: str) -> list[str]:
    if minecraft == "1.20.1":
        raise InstallError("NeoForge 从 1.20.2 开始提供独立版本，1.20.1 请使用 Forge。")
    parts = minecraft.split(".")
    if len(parts) < 2:
        raise InstallError("无法识别的 Minecraft 版本")
    prefix = f"{parts[1]}.{parts[2] if len(parts) > 2 else '0'}."
    url = f"{NEOFORGE_MAVEN}/net/neoforged/neoforge/maven-metadata.xml"
    result = [v for v in _maven_versions(ctx, url) if v.startswith(prefix)]
    return list(reversed(result))


# --------------------------------------------------------------------- Fabric / Quilt
def _download_profile_libraries(
    ctx: Any, profile: dict[str, Any], task: Any, label: str
) -> None:
    libraries_dir = Path(ctx.launcher.game_dir) / "libraries"
    items = []
    for lib in profile.get("libraries") or []:
        if not isinstance(lib, dict):
            continue
        if not rules_allow(lib.get("rules"), FEATURES):
            continue
        art = library_artifact(lib)
        if art and art.get("url"):
            items.append(
                {
                    "url": art["url"],
                    "dest": libraries_dir / art["path"],
                    "sha1": art.get("sha1", ""),
                    "size": art.get("size", 0),
                    "label": Path(art["path"]).name,
                }
            )
    _download_items(ctx, items, task, label)


def install_fabric(ctx: Any, minecraft: str, loader: str, task: Any) -> str:
    ensure_vanilla(ctx, minecraft, task)
    task.status("正在获取 Fabric 配置…")
    url = f"{FABRIC_META}/v2/versions/loader/{quote(minecraft)}/{quote(loader)}/profile/json"
    profile = ctx.http.get_json(url)
    if not isinstance(profile, dict) or not profile.get("id"):
        raise InstallError("Fabric 返回的配置无效")
    profile.setdefault("inheritsFrom", minecraft)
    _download_profile_libraries(ctx, profile, task, "正在下载 Fabric 依赖…")
    _ensure_java(ctx, _java_major_for(ctx, minecraft), task)
    vid = str(profile["id"])
    write_json(version_dir(ctx, vid) / f"{vid}.json", profile)
    task.status(f"Fabric {loader} 安装完成")
    _emit_installed(ctx, vid)
    return vid


def install_quilt(ctx: Any, minecraft: str, loader: str, task: Any) -> str:
    ensure_vanilla(ctx, minecraft, task)
    task.status("正在获取 Quilt 配置…")
    url = f"{QUILT_META}/v3/versions/loader/{quote(minecraft)}/{quote(loader)}/profile/json"
    profile = ctx.http.get_json(url)
    if not isinstance(profile, dict) or not profile.get("id"):
        raise InstallError("Quilt 返回的配置无效")
    profile.setdefault("inheritsFrom", minecraft)
    _download_profile_libraries(ctx, profile, task, "正在下载 Quilt 依赖…")
    _ensure_java(ctx, _java_major_for(ctx, minecraft), task)
    vid = str(profile["id"])
    write_json(version_dir(ctx, vid) / f"{vid}.json", profile)
    task.status(f"Quilt {loader} 安装完成")
    _emit_installed(ctx, vid)
    return vid


def _java_major_for(ctx: Any, minecraft: str) -> int:
    data = read_json(version_dir(ctx, minecraft) / f"{minecraft}.json") or {}
    try:
        return int((data.get("javaVersion") or {}).get("majorVersion") or 8)
    except (TypeError, ValueError):
        return 8


# --------------------------------------------------------------------- Forge / NeoForge
def _extract_zip_member(zf: zipfile.ZipFile, member: str, dest: Path) -> bool:
    try:
        info = zf.getinfo(member)
    except KeyError:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(info) as src, open(dest, "wb") as out:
        shutil.copyfileobj(src, out)
    return True


def _jar_main_class(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            text = zf.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise InstallError(f"无法读取处理器 {path.name}：{exc}") from exc
    for line in text.splitlines():
        if line.lower().startswith("main-class:"):
            return line.split(":", 1)[1].strip()
    raise InstallError(f"处理器 {path.name} 缺少 Main-Class")


def _library_path(name: str, game_dir: Path) -> Path:
    from mcs.core.launcher import maven_path

    return game_dir / "libraries" / maven_path(name)


def _install_forge_like(
    ctx: Any, installer_url: str, expected_id: str, task: Any, label: str
) -> str:
    game_dir = Path(ctx.launcher.game_dir)
    with tempfile.TemporaryDirectory(prefix="mcs-loader-") as temp:
        tempdir = Path(temp)
        installer_path = tempdir / "installer.jar"
        task.status(f"正在下载 {label} 安装器…")
        ctx.http.download(
            installer_url,
            installer_path,
            progress=lambda d, t, _m: task.progress(d, t, f"下载 {label} 安装器"),
            cancel=task.cancel_event,
        )
        task.check_cancelled()
        try:
            zf = zipfile.ZipFile(installer_path)
        except zipfile.BadZipFile as exc:
            raise InstallError(f"{label} 安装器损坏：{exc}") from exc
        with zf:
            try:
                profile = json.loads(zf.read("install_profile.json"))
            except KeyError as exc:
                raise InstallError(f"{label} 安装器缺少 install_profile.json") from exc
            install = profile.get("install") or profile
            minecraft = str(install.get("minecraft") or profile.get("minecraft") or "")
            if not minecraft:
                raise InstallError(f"{label} 安装器缺少 Minecraft 版本信息")
            ensure_vanilla(ctx, minecraft, task)
            version_id = str(
                expected_id
                or install.get("version")
                or profile.get("version")
                or f"{minecraft}-{label.lower()}"
            )
            version_json = None
            try:
                version_json = json.loads(zf.read("version.json"))
            except KeyError:
                version_json = install.get("versionInfo") or profile.get("versionInfo")
            if not isinstance(version_json, dict):
                raise InstallError(f"{label} 安装器缺少版本配置")
            version_json["id"] = version_id
            version_json.setdefault("inheritsFrom", minecraft)

            # 安装安装器声明的依赖库
            libs = install.get("libraries") or profile.get("libraries") or []
            items = []
            libraries_dir = game_dir / "libraries"
            for lib in libs:
                if not isinstance(lib, dict):
                    continue
                if not rules_allow(lib.get("rules"), FEATURES):
                    continue
                art = library_artifact(lib)
                if art and art.get("url"):
                    items.append(
                        {
                            "url": art["url"],
                            "dest": libraries_dir / art["path"],
                            "sha1": art.get("sha1", ""),
                            "size": art.get("size", 0),
                            "label": Path(art["path"]).name,
                        }
                    )
            _download_items(ctx, items, task, f"正在下载 {label} 依赖库…")

            # 把安装器内嵌的 maven 文件放到 libraries
            for name in zf.namelist():
                if not name.startswith("maven/") or not name.endswith(".jar"):
                    continue
                relative = name[len("maven/") :]
                target = libraries_dir / relative
                if target.is_file():
                    continue
                _extract_zip_member(zf, name, target)

            lzma_path = tempdir / "client.lzma"
            _extract_zip_member(zf, "data/client.lzma", lzma_path)

            # 版本 JSON 里的库也要存在
            vlibs = []
            for lib in version_json.get("libraries") or []:
                if not isinstance(lib, dict):
                    continue
                if not rules_allow(lib.get("rules"), FEATURES):
                    continue
                art = library_artifact(lib)
                if art and art.get("url"):
                    vlibs.append(
                        {
                            "url": art["url"],
                            "dest": libraries_dir / art["path"],
                            "sha1": art.get("sha1", ""),
                            "size": art.get("size", 0),
                            "label": Path(art["path"]).name,
                        }
                    )
            _download_items(ctx, vlibs, task, f"正在下载 {label} 组件…")

            # 处理器：现代 Forge/NeoForge 需要它们生成打补丁后的客户端
            processors = install.get("processors") or profile.get("processors") or []
            if processors:
                java_path = _ensure_java(ctx, _java_major_for(ctx, minecraft), task)
                args_vars: dict[str, str] = {
                    "{MINECRAFT_JAR}": str(
                        version_dir(ctx, minecraft) / f"{minecraft}.jar"
                    ),
                    "{INSTALLER}": str(installer_path),
                    "{BINPATCH}": str(lzma_path),
                    "{ROOT}": str(tempdir / "root"),
                    "{SIDE}": "client",
                }
                (tempdir / "root").mkdir(exist_ok=True)
                for key, value in (install.get("data") or profile.get("data") or {}).items():
                    if not isinstance(value, dict):
                        continue
                    token = "{" + key + "}"
                    if token in args_vars:
                        # BINPATCH 等变量必须指向本地解包结果，不能被安装器内的路径覆盖
                        continue
                    raw = str(value.get("client") or "")
                    if raw.startswith("[") and raw.endswith("]"):
                        args_vars[token] = str(_library_path(raw[1:-1], game_dir))
                    else:
                        args_vars[token] = raw
                total = max(1, len(processors))
                for index, processor in enumerate(processors):
                    task.check_cancelled()
                    if "client" not in (processor.get("sides") or ["client"]):
                        continue
                    jar_name = str(processor.get("jar") or "")
                    main_class = str(processor.get("mainClass") or "")
                    jar_path = _library_path(jar_name, game_dir)
                    if not main_class:
                        main_class = _jar_main_class(jar_path)
                    classpath = [
                        str(_library_path(str(c), game_dir))
                        for c in processor.get("classpath") or []
                    ]
                    classpath.append(str(jar_path))
                    command = [java_path, "-cp", os.pathsep.join(classpath), main_class]
                    for arg in processor.get("args") or []:
                        value = args_vars.get(arg, str(arg))
                        if value.startswith("[") and value.endswith("]"):
                            value = str(_library_path(value[1:-1], game_dir))
                        for key, replacement in args_vars.items():
                            value = value.replace(key, replacement)
                        command.append(value)
                    task.status(f"正在运行 {label} 处理器 {index + 1}/{total}…")
                    completed = subprocess.run(
                        command,
                        cwd=str(tempdir / "root"),
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    if completed.returncode != 0:
                        detail = (completed.stderr or completed.stdout or "").strip()
                        raise InstallError(
                            f"{label} 安装处理器失败（退出码 {completed.returncode}）\n{detail[-1200:]}"
                        )
                    task.progress(index + 1, total, f"{label} 处理器")

            # 把处理器生成的打补丁客户端放入版本目录，启动器会优先使用它
            patched_spec = str(((install.get("data") or {}).get("PATCHED") or {}).get("client") or "")
            if patched_spec.startswith("[") and patched_spec.endswith("]"):
                patched = _library_path(patched_spec[1:-1], game_dir)
                if patched.is_file():
                    target_dir = version_dir(ctx, version_id)
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target = target_dir / f"{version_id}.jar"
                    if not target.is_file() or target.stat().st_size != patched.stat().st_size:
                        shutil.copyfile(patched, target)

            write_json(version_dir(ctx, version_id) / f"{version_id}.json", version_json)
            # 旧版本 Forge 可能不写客户端 jar；启动器会自动回退到原版 jar。

    _ensure_java(ctx, _java_major_for(ctx, minecraft), task)
    task.status(f"{label} {version_id} 安装完成")
    _emit_installed(ctx, version_id)
    return version_id


def install_forge(ctx: Any, minecraft: str, loader: str, task: Any) -> str:
    full = f"{minecraft}-{loader}"
    url = f"{FORGE_MAVEN}/net/minecraftforge/forge/{full}/forge-{full}-installer.jar"
    return _install_forge_like(ctx, url, f"{minecraft}-forge-{loader}", task, "Forge")


def install_neoforge(ctx: Any, minecraft: str, loader: str, task: Any) -> str:
    url = f"{NEOFORGE_MAVEN}/net/neoforged/neoforge/{loader}/neoforge-{loader}-installer.jar"
    return _install_forge_like(ctx, url, f"neoforge-{loader}", task, "NeoForge")
