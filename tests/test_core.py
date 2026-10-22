"""核心单元的轻量测试：不访问网络、不启动 GUI。"""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path

logging.disable(logging.CRITICAL)

from mcs.api.hooks import HookBus
from mcs.core.launcher import _Log4jParser, maven_path
from mcs.core.net import rewrite_url
from mcs.plugins_host.manifest import ManifestError, load_manifest
from mcs.plugins_host.services import ServiceRegistry


class MirrorTest(unittest.TestCase):
    def test_neoforge_url_uses_reachable_mirror(self) -> None:
        url = "https://maven.neoforged.net/releases/net/neoforged/neoforge/21.1.264/neoforge-21.1.264-installer.jar"
        self.assertEqual(
            rewrite_url(url, "bmclapi"),
            "https://mirrors4.qlu.edu.cn/bmclapi/net/neoforged/neoforge/21.1.264/neoforge-21.1.264-installer.jar",
        )

    def test_official_mode_keeps_url(self) -> None:
        url = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
        self.assertEqual(rewrite_url(url, "official"), url)

    def test_default_mirror_rewrites_mojang(self) -> None:
        url = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
        self.assertTrue(rewrite_url(url, "bmclapi").startswith("https://bmclapi2.bangbang93.com"))


class MavenPathTest(unittest.TestCase):
    def test_group_and_artifact(self) -> None:
        self.assertEqual(
            maven_path("com.example:demo:1.2.3"),
            Path("com/example/demo/1.2.3/demo-1.2.3.jar").as_posix(),
        )

    def test_classifier_and_extension(self) -> None:
        self.assertEqual(
            maven_path("net.minecraftforge:forge:1.20.1-47.4.28:client"),
            Path("net/minecraftforge/forge/1.20.1-47.4.28/forge-1.20.1-47.4.28-client.jar").as_posix(),
        )
        self.assertEqual(
            maven_path("org.lwjgl:lwjgl:3.3.2:natives-windows@zip"),
            Path("org/lwjgl/lwjgl/3.3.2/lwjgl-3.3.2-natives-windows.zip").as_posix(),
        )


class Log4jParserTest(unittest.TestCase):
    def test_xml_events_become_readable_lines(self) -> None:
        parser = _Log4jParser()
        results = [
            parser.feed(
                '<log4j:Event logger="minecraft" timestamp="1" level="INFO" thread="Render thread">'
            ),
            parser.feed(
                "  <log4j:Message><![CDATA[Reloading ResourceManager: vanilla]]></log4j:Message>"
            ),
            parser.feed("</log4j:Event>"),
            parser.feed("plain jvm line"),
        ]
        self.assertEqual(
            results,
            [None, "[Render thread/INFO] Reloading ResourceManager: vanilla", None, "plain jvm line"],
        )


class HookBusTest(unittest.TestCase):
    def test_priority_and_unregister(self) -> None:
        bus = HookBus()
        calls: list[str] = []
        bus.register("demo", lambda: calls.append("late"), plugin_id="b", priority=200)
        token = bus.register("demo", lambda: calls.append("early"), plugin_id="a", priority=10)
        bus.emit("demo")
        self.assertEqual(calls, ["early", "late"])
        bus.unregister(token)
        bus.unregister_plugin("b")
        self.assertEqual(bus.count("demo"), 0)

    def test_failing_callback_does_not_block_others(self) -> None:
        bus = HookBus()
        calls: list[str] = []
        bus.register("demo", lambda: (_ for _ in ()).throw(RuntimeError("boom")), priority=1)
        bus.register("demo", lambda: calls.append("ok"), priority=2)
        bus.emit("demo")
        self.assertEqual(calls, ["ok"])


class ServiceRegistryTest(unittest.TestCase):
    def test_owner_cleanup(self) -> None:
        registry = ServiceRegistry()
        registry.register("java", object(), owner="mcs.java")
        self.assertIn("java", registry)
        self.assertEqual(registry.owner_of("java"), "mcs.java")
        registry.unregister_owner("mcs.java")
        self.assertNotIn("java", registry)

    def test_duplicate_name_rejected(self) -> None:
        registry = ServiceRegistry()
        registry.register("x", object(), owner="a")
        with self.assertRaises(KeyError):
            registry.register("x", object(), owner="b")


class ManifestTest(unittest.TestCase):
    def _write(self, directory: Path, payload: dict) -> None:
        (directory / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_valid_python_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self._write(
                directory,
                {
                    "id": "com.example.demo",
                    "name": "Demo",
                    "version": "1.2.3",
                    "api": 1,
                    "kind": "python",
                    "entry": "plugin.py",
                },
            )
            meta = load_manifest(directory, builtin=False)
            self.assertEqual(meta.id, "com.example.demo")
            self.assertEqual(meta.kind, "python")
            self.assertFalse(meta.builtin)

    def test_missing_id_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self._write(directory, {"name": "Demo", "entry": "plugin.py"})
            with self.assertRaises(ManifestError):
                load_manifest(directory, builtin=False)


if __name__ == "__main__":
    unittest.main()
