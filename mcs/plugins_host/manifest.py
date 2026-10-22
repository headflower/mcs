"""plugin.json 解析与校验。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import API_VERSION
from ..api.types import PluginMeta


class ManifestError(ValueError):
    pass


def load_manifest(plugin_dir: Path, *, builtin: bool) -> PluginMeta:
    path = plugin_dir / "plugin.json"
    if not path.is_file():
        raise ManifestError(f"缺少 plugin.json：{plugin_dir}")
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"无法读取 {path}：{exc}") from exc
    plugin_id = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or plugin_id).strip()
    version = str(raw.get("version") or "0.0.0")
    if not plugin_id or "/" in plugin_id or "\\" in plugin_id:
        raise ManifestError(f"{path} 的 id 非法")
    kind = str(raw.get("kind") or "python").lower()
    if kind not in ("python", "native"):
        raise ManifestError(f"{path} 的 kind 必须是 python 或 native")
    entry = str(raw.get("entry") or ("plugin.py" if kind == "python" else "")).strip()
    if not entry:
        raise ManifestError(f"{path} 缺少 entry")
    try:
        api = int(raw.get("api") or API_VERSION)
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"{path} 的 api 字段非法") from exc
    if api > API_VERSION:
        raise ManifestError(f"{name} 需要 API v{api}，当前启动器只支持 v{API_VERSION}")
    dependencies = raw.get("dependencies") or []
    if not isinstance(dependencies, list):
        dependencies = [str(dependencies)]
    return PluginMeta(
        id=plugin_id,
        name=name,
        version=version,
        api=api,
        kind=kind,
        entry=entry,
        description=str(raw.get("description") or ""),
        author=str(raw.get("author") or ""),
        dependencies=[str(d) for d in dependencies],
        priority=int(raw.get("priority") or 100),
        builtin=builtin,
        path=str(plugin_dir),
        abi=int(raw.get("abi") or 0),
    )
