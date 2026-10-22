from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from mcs.plugins_host.installer import PluginInstallError, install_zip, uninstall_plugin

MANIFEST = {
    "id": "com.example.demo",
    "name": "Demo",
    "version": "1.0.0",
    "api": 1,
    "kind": "python",
    "entry": "plugin.py",
}


class InstallerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.archive = self.root / "demo.zip"
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("demo/plugin.json", json.dumps(MANIFEST))
            archive.writestr("demo/plugin.py", "def setup(ctx):\n    return None\n")
            archive.writestr("demo/data/readme.txt", "hello")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_install_from_wrapped_directory(self) -> None:
        target = self.root / "plugins"
        meta = install_zip(self.archive, target_root=target)
        self.assertEqual(meta.id, "com.example.demo")
        self.assertEqual(meta.name, "Demo")
        self.assertTrue((target / "com.example.demo" / "plugin.py").is_file())
        self.assertTrue((target / "com.example.demo" / "data" / "readme.txt").is_file())

    def test_existing_requires_overwrite(self) -> None:
        target = self.root / "plugins"
        install_zip(self.archive, target_root=target)
        with self.assertRaises(PluginInstallError):
            install_zip(self.archive, target_root=target)
        meta = install_zip(self.archive, overwrite=True, target_root=target)
        self.assertTrue(Path(meta.path).is_dir())

    def test_rejects_path_traversal(self) -> None:
        bad = self.root / "bad.zip"
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("../evil.txt", "x")
            archive.writestr("plugin.json", "{}")
        with self.assertRaises(PluginInstallError):
            install_zip(bad, target_root=self.root / "plugins")
        self.assertFalse((self.root / "evil.txt").exists())

    def test_uninstall_only_owned_directory(self) -> None:
        target = self.root / "plugins"
        meta = install_zip(self.archive, target_root=target)
        uninstall_plugin(meta, plugin_root=target)
        self.assertFalse(Path(meta.path).exists())

    def test_builtin_plugin_is_not_removable(self) -> None:
        target = self.root / "plugins"
        meta = install_zip(self.archive, target_root=target)
        meta.builtin = True
        with self.assertRaises(PluginInstallError):
            uninstall_plugin(meta, plugin_root=target)


if __name__ == "__main__":
    unittest.main()
