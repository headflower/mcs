"""Minecraft 启动核心：版本解析、参数构建、进程管理。

这里只做“启动”，不负责下载游戏文件。缺失文件时会给出可读的错误，
引导用户通过官方游戏下载插件补齐。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from .. import __version__
from ..api.types import Account, InstalledVersion, JavaRuntimeInfo, LaunchOptions
from .java import JavaRegistry

log = logging.getLogger("mcs.launch")

WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000 if WINDOWS else 0
OS_NAME = "windows" if sys.platform == "win32" else ("osx" if sys.platform == "darwin" else "linux")
OS_ARCH = "x86_64" if sys.maxsize > 2**32 else "x86"


class LaunchError(RuntimeError):
    pass


@dataclass
class LaunchContext:
    version_id: str
    version: dict[str, Any]
    account: Account | None
    options: LaunchOptions
    command: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str = ""
    java: JavaRuntimeInfo | None = None


@dataclass
class ResolvedVersion:
    id: str
    data: dict[str, Any]
    chain: list[str]
    client_version_id: str
    raw: dict[str, Any]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise LaunchError(f"找不到版本文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise LaunchError(f"版本文件不是合法 JSON：{path}") from exc


def flatten_arg(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(flatten_arg(item))
        return result
    return []


def _rule_matches(rule: dict[str, Any], features: dict[str, bool]) -> bool:
    os_rule = rule.get("os")
    if os_rule:
        if os_rule.get("name") and os_rule["name"] != OS_NAME:
            return False
        arch = os_rule.get("arch")
        if arch:
            if arch == "x86" and OS_ARCH != "x86":
                return False
            if arch in ("x86_64", "amd64") and OS_ARCH not in ("x86_64", "amd64"):
                return False
            if arch == "arm64" and OS_ARCH != "arm64":
                return False
        version_regex = os_rule.get("version")
        if version_regex:
            import platform

            if not re.search(version_regex, platform.release()):
                return False
    for key, expected in (rule.get("features") or {}).items():
        if bool(features.get(key)) != bool(expected):
            return False
    return True


def rules_allow(rules: list[dict[str, Any]] | None, features: dict[str, bool]) -> bool:
    if not rules:
        return True
    allowed = False
    for rule in rules:
        if _rule_matches(rule, features):
            allowed = rule.get("action") == "allow"
    return allowed


def maven_path(name: str) -> str:
    if "@" in name:
        name, ext = name.rsplit("@", 1)
    else:
        ext = "jar"
    parts = name.split(":")
    if len(parts) < 3:
        return name.replace(":", "/") + "." + ext
    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = parts[3] if len(parts) > 3 else ""
    suffix = f"-{classifier}" if classifier else ""
    return f"{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}{suffix}.{ext}"


def library_artifact(lib: dict[str, Any]) -> dict[str, Any] | None:
    downloads = lib.get("downloads") or {}
    artifact = downloads.get("artifact")
    if artifact and artifact.get("path"):
        return {
            "path": artifact["path"],
            "url": artifact.get("url", ""),
            "sha1": artifact.get("sha1", ""),
            "size": artifact.get("size", 0),
        }
    name = lib.get("name", "")
    if not name:
        return None
    base = str(lib.get("url") or "https://libraries.minecraft.net/").rstrip("/")
    path = maven_path(name)
    return {"path": path, "url": f"{base}/{path}", "sha1": "", "size": 0}


def native_artifact(lib: dict[str, Any]) -> dict[str, Any] | None:
    natives = lib.get("natives") or {}
    classifier = natives.get("windows" if WINDOWS else ("osx" if sys.platform == "darwin" else "linux"))
    if not classifier:
        return None
    classifier = classifier.replace("${arch}", "64" if OS_ARCH == "x86_64" else "32")
    downloads = lib.get("downloads") or {}
    for key, item in (downloads.get("classifiers") or {}).items():
        if key == classifier:
            return {
                "path": item.get("path", ""),
                "url": item.get("url", ""),
                "sha1": item.get("sha1", ""),
                "size": item.get("size", 0),
            }
    name = lib.get("name", "")
    if ":" not in name:
        return None
    parts = name.split(":")
    base_name = ":".join(parts[:3]) + ":" + classifier
    base = str(lib.get("url") or "https://libraries.minecraft.net/").rstrip("/")
    path = maven_path(f"{base_name}@jar")
    return {"path": path, "url": f"{base}/{path}", "sha1": "", "size": 0}


class _Log4jParser:
    """把 Minecraft log4j XML 控制台输出还原成可读日志行。"""

    _EVENT = re.compile(r"<log4j:Event\b[^>]*>")
    _ATTR = re.compile(r'(\w+)="([^"]*)"')
    _CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.S)

    def __init__(self) -> None:
        self._in_event = False
        self._level = "INFO"
        self._thread = ""

    def feed(self, line: str) -> str | None:
        stripped = line.strip()
        if self._EVENT.search(stripped):
            attrs = dict(self._ATTR.findall(self._EVENT.search(stripped).group(0)))
            self._level = attrs.get("level", "INFO")
            self._thread = attrs.get("thread", "")
            self._in_event = True
            return None
        if not self._in_event:
            return line
        if stripped.startswith("</log4j:Event"):
            self._in_event = False
            return None
        if stripped.startswith(("<log4j:Message", "<log4j:Throwable")):
            match = self._CDATA.search(line)
            if not match:
                return None
            content = match.group(1)
            if stripped.startswith("<log4j:Message"):
                prefix = f"[{self._thread}/{self._level}] " if self._thread else f"[{self._level}] "
                return prefix + content
            return f"[{self._level}] {content}"
        return None


class LaunchService(QObject):
    versions_changed = pyqtSignal()
    log_line = pyqtSignal(str)
    launch_started = pyqtSignal(int)
    launch_finished = pyqtSignal(int)
    state_changed = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, settings: Any, accounts: Any = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.accounts = accounts
        self.java = JavaRegistry(settings)
        self.hooks: Any = None
        self._versions: list[InstalledVersion] | None = None
        self._process: subprocess.Popen | None = None
        self._stopping = False
        self._reader: threading.Thread | None = None

    # --------------------------------------------------------------- paths
    @property
    def game_dir(self) -> Path:
        return self.settings.game_dir

    @property
    def versions_dir(self) -> Path:
        return self.game_dir / "versions"

    @property
    def libraries_dir(self) -> Path:
        return self.game_dir / "libraries"

    @property
    def assets_dir(self) -> Path:
        return self.game_dir / "assets"

    # ------------------------------------------------------------- versions
    def _detect_loader(self, version_id: str, raw: dict[str, Any]) -> str:
        text = version_id.lower()
        if "neoforge" in text:
            return "neoforge"
        if "fabric" in text:
            return "fabric"
        if "quilt" in text:
            return "quilt"
        if "forge" in text:
            return "forge"
        for lib in raw.get("libraries") or []:
            name = str(lib.get("name", "")).lower()
            if "net.neoforged" in name:
                return "neoforge"
            if "net.fabricmc" in name:
                return "fabric"
            if "org.quiltmc" in name:
                return "quilt"
            if "net.minecraftforge" in name:
                return "forge"
        return "vanilla"

    def versions(self, refresh: bool = False) -> list[InstalledVersion]:
        if self._versions is not None and not refresh:
            return list(self._versions)
        items: list[InstalledVersion] = []
        if self.versions_dir.is_dir():
            for entry in sorted(self.versions_dir.iterdir(), key=lambda p: p.name.lower(), reverse=True):
                json_path = entry / f"{entry.name}.json"
                if not entry.is_dir() or not json_path.is_file():
                    continue
                try:
                    raw = _load_json(json_path)
                except LaunchError:
                    continue
                java_version = raw.get("javaVersion") or {}
                if not java_version and raw.get("inheritsFrom"):
                    try:
                        parent = _load_json(
                            self.versions_dir / str(raw["inheritsFrom"]) / f"{raw['inheritsFrom']}.json"
                        )
                        java_version = parent.get("javaVersion") or {}
                    except LaunchError:
                        java_version = {}
                items.append(
                    InstalledVersion(
                        id=entry.name,
                        name=str(raw.get("id") or entry.name),
                        type=str(raw.get("type") or "release"),
                        loader=self._detect_loader(entry.name, raw),
                        java_major=int(java_version.get("majorVersion") or 0),
                        path=str(entry),
                        release_time=str(raw.get("releaseTime") or ""),
                    )
                )
        self._versions = items
        return list(items)

    def refresh_versions(self) -> list[InstalledVersion]:
        result = self.versions(refresh=True)
        self.versions_changed.emit()
        return result

    def resolve(self, version_id: str, _seen: set[str] | None = None) -> ResolvedVersion:
        _seen = _seen or set()
        if version_id in _seen:
            raise LaunchError(f"版本继承出现循环：{version_id}")
        _seen.add(version_id)
        path = self.versions_dir / version_id / f"{version_id}.json"
        raw = _load_json(path)
        parent_id = raw.get("inheritsFrom")
        if not parent_id:
            return ResolvedVersion(version_id, raw, [version_id], self._find_client_jar(version_id, raw), raw)
        parent = self.resolve(str(parent_id), _seen)
        merged = json.loads(json.dumps(parent.data))
        merged["id"] = version_id
        merged["inheritsFrom"] = parent_id
        for key in ("type", "assets", "assetIndex", "downloads", "javaVersion", "logging", "complianceLevel", "releaseTime", "time"):
            if key in raw:
                merged[key] = raw[key]
        merged["mainClass"] = raw.get("mainClass") or parent.data.get("mainClass")
        if raw.get("minecraftArguments"):
            merged["minecraftArguments"] = raw["minecraftArguments"]
        if raw.get("arguments"):
            merged["arguments"] = self._merge_arguments(parent.data.get("arguments"), raw["arguments"])
        libraries: list[dict[str, Any]] = []
        index: dict[str, int] = {}
        for lib in list(parent.data.get("libraries") or []) + list(raw.get("libraries") or []):
            name = str(lib.get("name") or "")
            if name in index:
                libraries[index[name]] = lib
            else:
                index[name] = len(libraries)
                libraries.append(lib)
        merged["libraries"] = libraries
        if raw.get("jar"):
            merged["_jar"] = raw["jar"]
        elif parent.data.get("_jar"):
            merged["_jar"] = parent.data["_jar"]
        client_id = parent.client_version_id
        if (self.versions_dir / version_id / f"{version_id}.jar").is_file():
            client_id = version_id
        return ResolvedVersion(version_id, merged, [version_id] + parent.chain, client_id, raw)

    @staticmethod
    def _merge_arguments(parent: Any, child: Any) -> dict[str, Any]:
        parent = parent or {}
        child = child or {}
        result: dict[str, Any] = {}
        for key in ("game", "jvm"):
            result[key] = list(parent.get(key) or []) + list(child.get(key) or [])
        return result

    def _find_client_jar(self, version_id: str, raw: dict[str, Any]) -> str:
        jar = raw.get("jar")
        if jar and (self.versions_dir / jar / f"{jar}.jar").is_file():
            return jar
        if (self.versions_dir / version_id / f"{version_id}.jar").is_file():
            return version_id
        return version_id

    # ------------------------------------------------------------ features
    def _features(self, options: LaunchOptions) -> dict[str, bool]:
        return {
            "is_demo_user": bool(options.demo),
            "has_custom_resolution": bool(options.width and options.height),
            "has_quick_plays_support": False,
            "is_quick_play_singleplayer": False,
            "is_quick_play_multiplayer": False,
            "is_quick_play_realms": False,
        }

    def _collect_args(
        self,
        resolved: ResolvedVersion,
        options: LaunchOptions,
        replacements: dict[str, str],
    ) -> tuple[list[str], list[str]]:
        version = resolved.data
        features = self._features(options)
        jvm_args: list[str] = []
        game_args: list[str] = []
        args = version.get("arguments")
        if args:
            for key, target in (("jvm", jvm_args), ("game", game_args)):
                for entry in args.get(key) or []:
                    if isinstance(entry, str):
                        target.append(self._sub(entry, replacements))
                    elif isinstance(entry, dict):
                        if not rules_allow(entry.get("rules"), features):
                            continue
                        for arg in flatten_arg(entry.get("value")):
                            target.append(self._sub(arg, replacements))
        elif version.get("minecraftArguments"):
            game_args.extend(self._sub(part, replacements) for part in str(version["minecraftArguments"]).split())
        return jvm_args, game_args

    @staticmethod
    def _sub(text: str, repl: dict[str, str]) -> str:
        for key, value in repl.items():
            text = text.replace("${" + key + "}", value)
        return text

    # ------------------------------------------------------------- libraries
    def _select_libraries(self, resolved: ResolvedVersion, options: LaunchOptions) -> tuple[list[dict], list[dict]]:
        features = self._features(options)
        artifacts: list[dict[str, Any]] = []
        natives: list[dict[str, Any]] = []
        seen: set[str] = set()
        for lib in resolved.data.get("libraries") or []:
            if not rules_allow(lib.get("rules"), features):
                continue
            name = str(lib.get("name") or "")
            if name in seen:
                continue
            seen.add(name)
            if lib.get("natives"):
                native = native_artifact(lib)
                if native and native.get("path"):
                    natives.append(native)
                if not (lib.get("downloads") or {}).get("artifact"):
                    continue
            artifact = library_artifact(lib)
            if artifact and artifact.get("path"):
                artifacts.append(artifact)
        return artifacts, natives

    def _classpath(self, resolved: ResolvedVersion, options: LaunchOptions) -> tuple[list[str], list[dict]]:
        artifacts, natives = self._select_libraries(resolved, options)
        paths: list[str] = []
        missing: list[str] = []
        for item in artifacts:
            p = self.libraries_dir / item["path"]
            if not p.is_file():
                missing.append(item["path"])
            paths.append(str(p))
        client_jar = self.versions_dir / resolved.client_version_id / f"{resolved.client_version_id}.jar"
        if not client_jar.is_file():
            missing.append(str(client_jar.relative_to(self.game_dir)) if client_jar.is_relative_to(self.game_dir) else str(client_jar))
        else:
            paths.append(str(client_jar))
        if missing:
            preview = "\n".join(f"  · {m}" for m in missing[:6])
            more = f"\n  …以及另外 {len(missing) - 6} 个文件" if len(missing) > 6 else ""
            raise LaunchError(
                f"版本文件不完整，缺少 {len(missing)} 个文件：\n{preview}{more}\n\n"
                "请打开“游戏版本”插件页面重新安装或补齐该版本。"
            )
        return paths, natives

    def _prepare_natives(self, version_id: str, natives: list[dict[str, Any]]) -> Path:
        target = self.versions_dir / version_id / "natives"
        target.mkdir(parents=True, exist_ok=True)
        for native in natives:
            jar = self.libraries_dir / native["path"]
            if not jar.is_file():
                raise LaunchError(f"缺少本地库：{jar}\n请通过“游戏版本”插件重新安装该版本。")
            try:
                with zipfile.ZipFile(jar) as zf:
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        name = info.filename
                        if name.startswith("META-INF/") or name.endswith(".git") or name.endswith(".sha1"):
                            continue
                        dest = target / name
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, dest.open("wb") as dst:
                            shutil.copyfileobj(src, dst)
            except zipfile.BadZipFile as exc:
                raise LaunchError(f"本地库损坏：{jar}") from exc
        return target

    def _prepare_assets(self, resolved: ResolvedVersion, options: LaunchOptions) -> dict[str, Any]:
        version = resolved.data
        asset_index = version.get("assetIndex") or {}
        index_id = asset_index.get("id") or version.get("assets") or "legacy"
        index_path = self.assets_dir / "indexes" / f"{index_id}.json"
        if not index_path.is_file():
            raise LaunchError(
                f"缺少资源索引：{index_path}\n请通过“游戏版本”插件安装该版本。"
            )
        try:
            index = _load_json(index_path)
        except LaunchError:
            raise
        virtual = bool(index.get("virtual")) or bool(index.get("map_to_resources"))
        if virtual:
            self._materialize_legacy_assets(index_id, index)
        return {"id": index_id, "path": index_path, "index": index}

    def _materialize_legacy_assets(self, index_id: str, index: dict[str, Any]) -> None:
        target = self.assets_dir / ("virtual" if index.get("virtual") else "..") / index_id
        if not index.get("virtual"):
            target = self.game_dir / "resources"
        marker = target / ".mcs-complete"
        if marker.is_file():
            return
        objects = index.get("objects") or {}
        for name, entry in objects.items():
            hash_value = str(entry.get("hash", ""))
            if len(hash_value) < 2:
                continue
            src = self.assets_dir / "objects" / hash_value[:2] / hash_value
            if not src.is_file():
                continue
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                try:
                    os.link(src, dest)
                except OSError:
                    shutil.copy2(src, dest)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("ok", encoding="utf-8")

    # ---------------------------------------------------------------- build
    def _options(self, options: LaunchOptions | None) -> LaunchOptions:
        if options is not None:
            return options
        return LaunchOptions(
            memory_mb=self.settings.memory_mb,
            jvm_args=str(self.settings.get("jvm_args") or ""),
            game_args=str(self.settings.get("game_args") or ""),
            fullscreen=bool(self.settings.get("fullscreen")),
            java_path=str(self.settings.get("java_path") or ""),
        )

    def _required_java(self, resolved: ResolvedVersion) -> int:
        java_version = resolved.data.get("javaVersion") or {}
        try:
            return int(java_version.get("majorVersion") or 8)
        except (TypeError, ValueError):
            return 8

    def build_command(
        self, version_id: str, options: LaunchOptions | None = None, account: Account | None = None
    ) -> list[str]:
        ctx = self._build_context(version_id, self._options(options), account)
        return ctx.command

    def _build_context(
        self, version_id: str, options: LaunchOptions, account: Account | None, require_files: bool = True
    ) -> LaunchContext:
        resolved = self.resolve(version_id)
        required_java = self._required_java(resolved)
        java = self.java.find(required_java, options.java_path)
        if java is None:
            raise LaunchError(
                f"未找到 Java {required_java} 或更高版本。\n"
                "请在“Java 运行时”插件页面下载，或在设置中手动指定 java.exe。"
            )
        if require_files:
            classpath, natives = self._classpath(resolved, options)
            natives_dir = self._prepare_natives(version_id, natives)
            assets = self._prepare_assets(resolved, options)
        else:
            classpath = [str(self.versions_dir / resolved.client_version_id / f"{resolved.client_version_id}.jar")]
            natives_dir = self.versions_dir / version_id / "natives"
            assets = {"id": "legacy"}

        account = account
        if account is None:
            account = Account(id="0", name="Player", uuid="00000000000000000000000000000000")
        replacements = {
            "auth_player_name": account.name,
            "auth_uuid": account.uuid.replace("-", ""),
            "auth_access_token": account.access_token or "0",
            "auth_xuid": "",
            "user_type": "msa" if account.kind == "microsoft" else "legacy",
            "clientid": "",
            "auth_session": account.access_token or "0",
            "version_name": version_id,
            "version_type": str(resolved.data.get("type") or "release"),
            "game_directory": str(self.game_dir),
            "game_assets": str(self.assets_dir / "virtual" / str(assets["id"])),
            "assets_root": str(self.assets_dir),
            "assets_index_name": str(assets["id"]),
            "natives_directory": str(natives_dir),
            "library_directory": str(self.libraries_dir),
            "classpath_separator": os.pathsep,
            "classpath": os.pathsep.join(classpath),
            "launcher_name": "MCSLauncher",
            "launcher_version": __version__,
            "primary_jar": str(self.versions_dir / resolved.client_version_id / f"{resolved.client_version_id}.jar"),
            "resolution_width": str(options.width or 854),
            "resolution_height": str(options.height or 480),
            "quickPlayPath": str(self.game_dir / "quickPlay" / "quickPlay.json"),
            "user_properties": "{}",
        }
        jvm_args, game_args = self._collect_args(resolved, options, replacements)

        if not any(arg in ("-cp", "-classpath") for arg in jvm_args):
            jvm_args = ["-Djava.library.path=" + str(natives_dir), "-cp", os.pathsep.join(classpath)] + jvm_args
        else:
            if not any("java.library.path" in arg for arg in jvm_args):
                jvm_args.insert(0, "-Djava.library.path=" + str(natives_dir))

        memory = max(512, int(options.memory_mb or 4096))
        command = [str(java.path)]
        command += [f"-Xmx{memory}M", f"-Xms{min(1024, memory // 2)}M"]
        if options.jvm_args:
            command += shlex.split(options.jvm_args, posix=True)
        command += [arg for arg in jvm_args if arg]
        logging_conf = (resolved.data.get("logging") or {}).get("client") or {}
        if logging_conf:
            file_info = logging_conf.get("file") or {}
            conf_path = self.assets_dir / "log_configs" / str(file_info.get("id") or "")
            if file_info.get("id") and conf_path.is_file():
                arg = str(logging_conf.get("argument") or "").replace("${path}", str(conf_path))
                if arg:
                    command.append(arg)
        main_class = str(resolved.data.get("mainClass") or "net.minecraft.client.main.Main")
        command.append(main_class)
        command += game_args
        if options.game_args:
            command += shlex.split(options.game_args, posix=True)
        if options.extra_jvm_args:
            command[1:1] = list(options.extra_jvm_args)
        if options.extra_game_args:
            command += list(options.extra_game_args)
        if options.fullscreen:
            command.append("--fullscreen")
        if options.width and options.height:
            command += ["--width", str(options.width), "--height", str(options.height)]

        env = os.environ.copy()
        env["MCS_LAUNCHER"] = __version__
        env.setdefault("JAVA_HOME", str(Path(java.path).parent.parent))
        return LaunchContext(
            version_id=version_id,
            version=resolved.data,
            account=account,
            options=options,
            command=command,
            env=env,
            cwd=str(self.game_dir),
            java=java,
        )

    # --------------------------------------------------------------- launch
    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def launch(self, version_id: str, options: LaunchOptions | None = None) -> bool:
        if self.running:
            raise LaunchError("游戏已经在运行。")
        account = self.accounts.current if self.accounts is not None else None
        if account is None:
            raise LaunchError("请先登录 Microsoft 正版账户。")
        if account.expired:
            raise LaunchError("登录状态已过期，请重新登录后再启动。")
        options = self._options(options)
        context = self._build_context(version_id, options, account)
        if self.hooks is not None:
            try:
                self.hooks.emit("launch.pre", context=context)
            except Exception:
                log.exception("launch.pre 钩子执行失败")
        self.game_dir.mkdir(parents=True, exist_ok=True)
        creationflags = CREATE_NO_WINDOW
        try:
            self._process = subprocess.Popen(
                context.command,
                cwd=context.cwd,
                env=context.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
        except OSError as exc:
            self._process = None
            raise LaunchError(f"无法启动 Java 进程：{exc}") from exc
        self._stopping = False
        self.settings.set("last_version", version_id, save=True)
        self.log_line.emit(f"[MCS] 使用 {context.java.label if context.java else 'Java'} 启动 {version_id}")
        log.info("[游戏] 使用 %s 启动 %s", context.java.label if context.java else "Java", version_id)
        java_label = Path(context.java.path).name if context.java else "java"
        message = f"[MCS] 正在启动 {version_id}（{java_label}，{len(context.command)} 个参数）"
        self.log_line.emit(message)
        log.info("[游戏] 正在启动 %s（%s，%s 个参数）", version_id, java_label, len(context.command))
        self.launch_started.emit(int(self._process.pid))
        self.state_changed.emit(True)
        if self.hooks is not None:
            self.hooks.emit("launch.started", context=context, pid=int(self._process.pid))
        self._reader = threading.Thread(target=self._read_output, args=(self._process,), daemon=True)
        self._reader.start()
        return True

    def _read_output(self, process: subprocess.Popen) -> None:
        parser = _Log4jParser()
        try:
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.rstrip("\r\n")
                visible = parser.feed(line)
                if visible is None:
                    continue
                self.log_line.emit(visible)
                log.info("[游戏] %s", visible)
                if self.hooks is not None:
                    self.hooks.emit("launch.log", line=visible)
        except Exception:
            log.exception("读取游戏输出失败")
        code = process.wait()
        self._process = None
        self.state_changed.emit(False)
        self.launch_finished.emit(code)
        if self.hooks is not None:
            self.hooks.emit("launch.finished", exit_code=code)
        self.log_line.emit(f"[MCS] 游戏进程已退出（代码 {code}）")
        log.info("[游戏] 游戏进程已退出（代码 %s）", code)

    def stop(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        self._stopping = True
        self.log_line.emit("[MCS] 正在结束游戏进程…")
        log.info("[游戏] 正在结束游戏进程")
        try:
            process.terminate()
        except OSError:
            return

        def force_kill() -> None:
            time.sleep(6)
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass

        threading.Thread(target=force_kill, daemon=True).start()
