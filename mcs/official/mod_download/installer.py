"""把模组文件下载到游戏目录，并按需递归安装必需依赖。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from mcs.api.hooks import HOOK_MOD_INSTALLED
from mcs.api.types import ModFile, ModProject

from .api import CurseForgeClient, ModApiError, ModrinthClient, client_for

SAFE_NAME = re.compile(r"[^A-Za-z0-9._+\-]")


def mods_dir(ctx: Any) -> Path:
    path = Path(ctx.launcher.game_dir) / "mods"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _filename(file: ModFile) -> str:
    name = file.filename or unquote(Path(urlparse(file.download_url).path).name)
    name = SAFE_NAME.sub("_", name).strip("._")
    if not name:
        name = f"{file.project_id or 'mod'}-{file.id}.jar"
    if not name.lower().endswith((".jar", ".zip")):
        name += ".jar"
    return name


def _pick_version(files: list[ModFile], game_version: str, loader: str) -> ModFile | None:
    if not files:
        return None
    candidates = [f for f in files if f.download_url]
    if game_version:
        exact = [f for f in candidates if game_version in f.game_versions]
        if exact:
            candidates = exact
    if loader:
        matching = [f for f in candidates if loader in f.loaders]
        if matching:
            candidates = matching
    return candidates[0] if candidates else None


def _required_modrinth_dependencies(
    ctx: Any, client: ModrinthClient, file: ModFile, game_version: str, loader: str
) -> list[ModFile]:
    result: list[ModFile] = []
    for dep in file.dependencies or []:
        if str(dep.get("dependency_type") or "") != "required":
            continue
        project_id = str(dep.get("project_id") or "")
        if not project_id:
            continue
        try:
            versions = client.versions(project_id, game_version=game_version, loader=loader)
        except Exception:  # noqa: BLE001
            ctx.logger.warning("获取 Modrinth 依赖 %s 失败", project_id, exc_info=True)
            continue
        picked = _pick_version(versions, game_version, loader)
        if picked:
            result.append(picked)
    return result


def _required_curseforge_dependencies(
    ctx: Any, client: CurseForgeClient, file: ModFile, game_version: str, loader: str
) -> list[ModFile]:
    result: list[ModFile] = []
    for dep in file.dependencies or []:
        if int(dep.get("relationType") or 0) != 3:
            continue
        mod_id = str(dep.get("modId") or "")
        if not mod_id:
            continue
        try:
            versions = client.versions(mod_id, game_version=game_version, loader=loader)
        except Exception:  # noqa: BLE001
            ctx.logger.warning("获取 CurseForge 依赖 %s 失败", mod_id, exc_info=True)
            continue
        picked = _pick_version(versions, game_version, loader)
        if picked:
            result.append(picked)
    return result


def install(
    ctx: Any,
    project: ModProject,
    file: ModFile,
    task: Any,
    *,
    game_version: str = "",
    loader: str = "",
    include_dependencies: bool = True,
) -> list[Path]:
    if not file.download_url:
        raise ModApiError(
            "该文件没有可用的下载地址。CurseForge 作者可能关闭了第三方下载，请到项目页面手动下载。"
        )
    target_dir = mods_dir(ctx)
    client = client_for(ctx, file.source)
    downloaded: list[Path] = []
    seen_files: set[str] = set()
    seen_projects: set[str] = {project.id}

    def download_one(item: ModFile, label: str) -> Path:
        task.check_cancelled()
        filename = _filename(item)
        dest = target_dir / filename
        task.status(f"正在下载 {label} · {filename}")
        path = ctx.http.download(
            item.download_url,
            dest,
            sha1=getattr(item, "sha1", ""),
            progress=lambda done, total, msg: task.progress(
                done, total, f"下载 {label}" if total else msg
            ),
            cancel=task.cancel_event,
        )
        downloaded.append(path)
        try:
            ctx.host.hooks.emit(
                HOOK_MOD_INSTALLED, project=project, file=item, path=str(path), source=item.source
            )
        except Exception:  # noqa: BLE001
            ctx.logger.exception("发送 mod.installed 钩子失败")
        return path

    def visit(item: ModFile, depth: int) -> None:
        if item.id in seen_files or depth > 5:
            return
        seen_files.add(item.id)
        label = item.name or item.filename or item.project_id
        download_one(item, label)
        if not include_dependencies:
            return
        if isinstance(client, ModrinthClient):
            deps = _required_modrinth_dependencies(ctx, client, item, game_version, loader)
        else:
            deps = _required_curseforge_dependencies(ctx, client, item, game_version, loader)
        for dep in deps:
            if dep.project_id in seen_projects:
                continue
            seen_projects.add(dep.project_id)
            task.status(f"安装依赖 {dep.name or dep.project_id}…")
            visit(dep, depth + 1)

    visit(file, 0)
    task.status(f"已安装 {len(downloaded)} 个文件到 mods")
    return downloaded
