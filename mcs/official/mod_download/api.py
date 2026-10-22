"""Modrinth 与 CurseForge 的只读 API 封装。

两个渠道统一返回 :class:`ModProject` / :class:`ModFile`。这里不负责写文件，
下载与安装由 installer.py 完成，便于 UI 与任务层复用。
"""

from __future__ import annotations

import json
import re
from typing import Any

from mcs.api.types import ModFile, ModProject

MODRINTH_API = "https://api.modrinth.com/v2"
CURSEFORGE_API = "https://api.curseforge.com/v1"
CURSEFORGE_GAME_ID = 432
CURSEFORGE_MOD_CLASS = 6
MODRINTH_HEADERS = {"User-Agent": "MCSLauncher/1.0.0 (mod-download plugin)"}

CF_LOADERS = {"fabric": 4, "quilt": 5, "forge": 1, "neoforge": 6}
CF_RELEASE = {1: "release", 2: "beta", 3: "alpha"}
MC_VERSION_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?$")
LOADER_NAMES = {
    "fabric": "fabric",
    "quilt": "quilt",
    "forge": "forge",
    "neoforge": "neoforge",
}


class ModApiError(RuntimeError):
    pass


def _modrinth_facets(game_version: str, loader: str) -> str:
    facets: list[list[str]] = [["project_type:mod"]]
    if game_version:
        facets.append([f"versions:{game_version}"])
    if loader in LOADER_NAMES:
        facets.append([f"categories:{LOADER_NAMES[loader]}"])
    return json.dumps(facets)


class ModrinthClient:
    source = "modrinth"

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    def search(
        self,
        query: str,
        *,
        game_version: str = "",
        loader: str = "",
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[ModProject], int]:
        data = self.ctx.http.get_json(
            f"{MODRINTH_API}/search",
            query=query or "",
            limit=limit,
            offset=offset,
            index="relevance" if query else "downloads",
            facets=_modrinth_facets(game_version, loader),
            headers=MODRINTH_HEADERS,
        )
        hits = data.get("hits") or []
        projects = [
            ModProject(
                id=str(hit.get("project_id") or ""),
                title=str(hit.get("title") or ""),
                description=str(hit.get("description") or ""),
                author=str(hit.get("author") or ""),
                downloads=int(hit.get("downloads") or 0),
                icon_url=str(hit.get("icon_url") or ""),
                source="modrinth",
                url=f"https://modrinth.com/mod/{hit.get('slug') or hit.get('project_id')}",
                categories=[str(c) for c in hit.get("categories") or []],
            )
            for hit in hits
            if hit.get("project_id")
        ]
        return projects, int(data.get("total_hits") or len(projects))

    def versions(
        self, project_id: str, *, game_version: str = "", loader: str = ""
    ) -> list[ModFile]:
        params: dict[str, Any] = {"headers": MODRINTH_HEADERS}
        if game_version:
            params["game_versions"] = json.dumps([game_version])
        if loader in LOADER_NAMES:
            params["loaders"] = json.dumps([LOADER_NAMES[loader]])
        data = self.ctx.http.get_json(f"{MODRINTH_API}/project/{project_id}/version", **params)
        files: list[ModFile] = []
        for version in data or []:
            primary = next(
                (f for f in version.get("files") or [] if f.get("primary")),
                (version.get("files") or [None])[0],
            )
            if not primary:
                continue
            hashes = primary.get("hashes") or {}
            files.append(
                ModFile(
                    id=str(version.get("id") or ""),
                    name=str(version.get("name") or primary.get("filename") or ""),
                    version=str(version.get("version_number") or ""),
                    download_url=str(primary.get("url") or ""),
                    filename=str(primary.get("filename") or ""),
                    game_versions=[str(g) for g in version.get("game_versions") or []],
                    loaders=[str(load) for load in version.get("loaders") or []],
                    dependencies=list(version.get("dependencies") or []),
                    release_type=str(version.get("version_type") or "release"),
                    source="modrinth",
                    project_id=str(version.get("project_id") or project_id),
                )
            )
            files[-1].sha1 = str(hashes.get("sha1") or "")
        return files

    def project_url(self, project_id: str) -> str:
        return f"https://modrinth.com/mod/{project_id}"


class CurseForgeClient:
    source = "curseforge"

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    @property
    def api_key(self) -> str:
        return str(self.ctx.settings.get("curseforge_api_key") or "").strip()

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ModApiError(
                "CurseForge 需要 API Key。请先在「设置 → 网络与下载」中填写 CurseForge API Key。"
            )
        return {"x-api-key": self.api_key, "Accept": "application/json"}

    def _get(self, path: str, **params: Any) -> Any:
        try:
            return self.ctx.http.get_json(
                f"{CURSEFORGE_API}{path}", headers=self._headers(), **params
            )
        except RuntimeError as exc:
            text = str(exc)
            if "401" in text or "403" in text:
                raise ModApiError("CurseForge 拒绝了请求，请检查 API Key 是否有效。") from exc
            raise

    def search(
        self,
        query: str,
        *,
        game_version: str = "",
        loader: str = "",
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[ModProject], int]:
        params: dict[str, Any] = {
            "gameId": CURSEFORGE_GAME_ID,
            "classId": CURSEFORGE_MOD_CLASS,
            "searchFilter": query or "",
            "sortField": 2,
            "sortOrder": "desc",
            "pageSize": limit,
            "index": offset,
        }
        if game_version:
            params["gameVersion"] = game_version
        if loader in CF_LOADERS:
            params["modLoaderType"] = CF_LOADERS[loader]
        data = self._get("/mods/search", **params)
        projects = []
        for mod in data.get("data") or []:
            logo = mod.get("logo") or {}
            links = mod.get("links") or {}
            projects.append(
                ModProject(
                    id=str(mod.get("id") or ""),
                    title=str(mod.get("name") or ""),
                    description=str(mod.get("summary") or ""),
                    author=", ".join(str(a.get("name")) for a in mod.get("authors") or [] if a.get("name")),
                    downloads=int(mod.get("downloadCount") or 0),
                    icon_url=str(logo.get("thumbnailUrl") or ""),
                    source="curseforge",
                    url=str(links.get("websiteUrl") or ""),
                    categories=[
                        str(c.get("name"))
                        for c in mod.get("categories") or []
                        if c.get("name")
                    ],
                )
            )
        total = int((data.get("pagination") or {}).get("totalCount") or len(projects))
        return projects, total

    def versions(
        self, project_id: str, *, game_version: str = "", loader: str = ""
    ) -> list[ModFile]:
        params: dict[str, Any] = {"pageSize": 50}
        if game_version:
            params["gameVersion"] = game_version
        if loader in CF_LOADERS:
            params["modLoaderType"] = CF_LOADERS[loader]
        data = self._get(f"/mods/{project_id}/files", **params)
        files: list[ModFile] = []
        for item in data.get("data") or []:
            values = [str(v) for v in item.get("gameVersions") or []]
            loaders = [v.lower() for v in values if v.lower() in LOADER_NAMES]
            game_versions = [v for v in values if MC_VERSION_RE.match(v)]
            files.append(
                ModFile(
                    id=str(item.get("id") or ""),
                    name=str(item.get("displayName") or item.get("fileName") or ""),
                    version=str(item.get("displayName") or ""),
                    download_url=str(item.get("downloadUrl") or ""),
                    filename=str(item.get("fileName") or ""),
                    game_versions=game_versions,
                    loaders=loaders,
                    dependencies=list(item.get("dependencies") or []),
                    release_type=CF_RELEASE.get(int(item.get("releaseType") or 1), "release"),
                    source="curseforge",
                    project_id=str(project_id),
                )
            )
        files.sort(key=lambda f: f.id, reverse=True)
        return files

    def project_url(self, project_id: str) -> str:
        return f"https://www.curseforge.com/minecraft/mc-mods/{project_id}"


def client_for(ctx: Any, source: str) -> ModrinthClient | CurseForgeClient:
    return CurseForgeClient(ctx) if source == "curseforge" else ModrinthClient(ctx)
