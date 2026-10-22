"""HTTP 下载与镜像处理。"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

import requests

from .. import MINECRAFT_USER_AGENT, __version__
from ..api.types import DownloadItem, TaskCancelled

log = logging.getLogger("mcs.http")

CHUNK = 256 * 1024
DEFAULT_TIMEOUT = 30

MIRROR_MAP = {
    "https://launchermeta.mojang.com": "https://bmclapi2.bangbang93.com",
    "https://piston-meta.mojang.com": "https://bmclapi2.bangbang93.com",
    "https://launcher.mojang.com": "https://bmclapi2.bangbang93.com",
    "https://resources.download.minecraft.net": "https://bmclapi2.bangbang93.com/assets",
    "https://libraries.minecraft.net": "https://bmclapi2.bangbang93.com/maven",
    "https://meta.fabricmc.net": "https://bmclapi2.bangbang93.com/fabric-meta",
    "https://meta.quiltmc.org": "https://bmclapi2.bangbang93.com/quilt-meta",
}


def rewrite_url(url: str, mirror: str) -> str:
    if mirror != "bmclapi" or not url:
        return url
    parsed = urlparse(url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    if parsed.netloc == "maven.neoforged.net" and parsed.path.startswith("/releases/"):
        # BMCLAPI 的 NeoForge maven 不包含 releases 前缀；其存储节点常不可达，
        # 优先使用高校镜像，由 _candidates 再回退到 BMCLAPI / Central / 官方。
        path = parsed.path[len("/releases") :]
        return "https://mirrors4.qlu.edu.cn/bmclapi" + path + (
            f"?{parsed.query}" if parsed.query else ""
        )
    replacement = MIRROR_MAP.get(root)
    if replacement:
        return replacement + parsed.path + (f"?{parsed.query}" if parsed.query else "")
    if parsed.netloc == "resources.download.minecraft.net":
        return url
    return url


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


class HttpClient:
    """插件可用的同步 HTTP 客户端。下载支持校验、镜像与取消。"""

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": f"{MINECRAFT_USER_AGENT} (+https://github.com/)",
                "Accept-Encoding": "gzip, deflate",
            }
        )
        self._lock = threading.Lock()
        self._mirror_ok = True
        self._mirror_key = self.mirror

    @property
    def mirror(self) -> str:
        if self._settings is None:
            return "official"
        return str(self._settings.get("download_mirror") or "official")

    def _url(self, url: str) -> str:
        current = self.mirror
        with self._lock:
            if current != self._mirror_key:
                self._mirror_key = current
                self._mirror_ok = True
            if not self._mirror_ok and "maven.neoforged.net" not in url:
                return url
        return rewrite_url(url, current)

    def _candidates(self, url: str) -> list[str]:
        mirrored = self._url(url)
        urls = [mirrored]
        parsed = urlparse(url)
        if parsed.netloc == "maven.neoforged.net" and parsed.path.startswith("/releases/"):
            relative = parsed.path[len("/releases") :]
            urls.append("https://bmclapi2.bangbang93.com/maven" + relative)
            # NeoForge 的依赖里有不少其实来自 Maven Central，镜像未收录时可用官方中央仓库
            if not relative.startswith("/net/neoforged/"):
                urls.append("https://repo1.maven.org/maven2" + relative)
        urls.append(url)
        unique: list[str] = []
        for item in urls:
            if item and item not in unique:
                unique.append(item)
        return unique

    def _mark_mirror_broken(self) -> None:
        with self._lock:
            if self._mirror_ok and self.mirror == "bmclapi":
                self._mirror_ok = False
                log.warning("BMCLAPI 镜像不可用，本次运行已切换到官方源")

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
        last: Exception | None = None
        candidates = self._candidates(url)
        for position, target in enumerate(candidates):
            for attempt in range(3):
                try:
                    resp = self._session.request(method, target, **kwargs)
                    if position == 0 and len(candidates) > 1 and resp.status_code >= 400:
                        last = RuntimeError(f"镜像返回 {resp.status_code}: {target}")
                        break
                    if resp.status_code >= 500 and attempt < 2:
                        time.sleep(0.6 * (attempt + 1))
                        continue
                    if position > 0 and "maven.neoforged.net" not in url:
                        self._mark_mirror_broken()
                    return resp
                except requests.RequestException as exc:
                    last = exc
                    if attempt < 2:
                        time.sleep(0.6 * (attempt + 1))
            if position == 0 and len(candidates) > 1 and "maven.neoforged.net" not in url:
                self._mark_mirror_broken()
        raise RuntimeError(f"网络请求失败：{url}（{last}）") from last

    def get_json(self, url: str, **params: Any) -> Any:
        headers = params.pop("headers", None)
        timeout = params.pop("timeout", DEFAULT_TIMEOUT)
        resp = self.request("GET", url, params=params or None, headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            raise RuntimeError(f"接口返回 {resp.status_code}：{url}")
        try:
            return resp.json()
        except ValueError as exc:
            raise RuntimeError(f"接口返回的不是 JSON：{url}") from exc

    def get_text(self, url: str, **params: Any) -> str:
        resp = self.request("GET", url, params=params or None)
        if resp.status_code >= 400:
            raise RuntimeError(f"接口返回 {resp.status_code}：{url}")
        return resp.text

    def post_json(self, url: str, payload: Any, **params: Any) -> Any:
        resp = self.request("POST", url, json=payload, **params)
        if resp.status_code >= 400:
            raise RuntimeError(f"接口返回 {resp.status_code}：{resp.text[:300]}")
        return resp.json()

    # -------------------------------------------------------------- download
    def download(
        self,
        url: str,
        dest: str | Path,
        *,
        sha1: str = "",
        expected_size: int = 0,
        progress: Callable[[int, int, str], None] | None = None,
        cancel: Any = None,
    ) -> Path:
        dest = Path(dest)
        if dest.exists() and dest.is_file():
            if expected_size and dest.stat().st_size != expected_size:
                pass
            elif not sha1 or sha1_file(dest).lower() == sha1.lower():
                if progress:
                    size = dest.stat().st_size
                    progress(size, size, dest.name)
                return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        last_error: Exception | None = None
        candidates = self._candidates(url)
        for position, target in enumerate(candidates):
            for attempt in range(2):
                if cancel is not None and getattr(cancel, "is_set", lambda: False)():
                    raise TaskCancelled()
                try:
                    with self._session.get(
                        target,
                        stream=True,
                        timeout=(15, 120),
                        headers={"Accept-Encoding": "identity"},
                    ) as resp:
                        if resp.status_code >= 400:
                            raise RuntimeError(f"下载失败 {resp.status_code}：{target}")
                        total = expected_size or int(resp.headers.get("Content-Length") or 0)
                        digest = hashlib.sha1() if sha1 else None
                        done = 0
                        with tmp.open("wb") as fh:
                            for chunk in resp.iter_content(CHUNK):
                                if cancel is not None and getattr(cancel, "is_set", lambda: False)():
                                    raise TaskCancelled()
                                if not chunk:
                                    continue
                                fh.write(chunk)
                                done += len(chunk)
                                if digest is not None:
                                    digest.update(chunk)
                                if progress:
                                    progress(done, total, dest.name)
                    if sha1 and digest is not None and digest.hexdigest().lower() != sha1.lower():
                        raise RuntimeError(f"文件校验失败：{dest.name}")
                    os.replace(tmp, dest)
                    if position > 0 and "maven.neoforged.net" not in url:
                        self._mark_mirror_broken()
                    return dest
                except TaskCancelled:
                    tmp.unlink(missing_ok=True)
                    raise
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    tmp.unlink(missing_ok=True)
                    if attempt == 0:
                        time.sleep(0.5)
            if position == 0 and len(candidates) > 1:
                self._mark_mirror_broken()
        raise RuntimeError(f"下载 {url} 失败：{last_error}") from last_error

    def download_many(
        self,
        items: Iterable[DownloadItem],
        *,
        workers: int = 6,
        progress: Callable[[int, int, str], None] | None = None,
        cancel: Any = None,
    ) -> list[Path]:
        items = [it for it in items if it.url and it.dest]
        if not items:
            return []
        total_known = sum(int(it.size or 0) for it in items)
        done_bytes = 0
        done_count = 0
        lock = threading.Lock()
        results: list[Path] = []

        def report(item_done: int, total: int, label: str) -> None:
            nonlocal done_bytes
            if progress is None:
                return
            with lock:
                pct_done = done_count
                bytes_done = done_bytes + item_done
            progress(bytes_done, total_known, f"{label}（{pct_done}/{len(items)}）")

        def worker(item: DownloadItem) -> Path:
            nonlocal done_bytes, done_count
            path = self.download(
                item.url,
                item.dest,
                sha1=item.sha1,
                expected_size=item.size,
                progress=lambda d, t, label, item=item: report(d, t, label),
                cancel=cancel,
            )
            with lock:
                done_bytes += int(item.size or (path.stat().st_size if path.exists() else 0))
                done_count += 1
            if progress:
                progress(done_bytes, total_known, item.label or Path(item.dest).name)
            return path

        with ThreadPoolExecutor(max_workers=max(1, min(workers, 12))) as pool:
            futures = {pool.submit(worker, item): item for item in items}
            for future in as_completed(futures):
                results.append(future.result())
        return results
