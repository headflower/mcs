"""主题与强调色对比度测试。"""

from __future__ import annotations

import unittest

from mcs.ui.theme import DEFAULT_ACCENT, build_stylesheet, _ink


class AccentThemeTest(unittest.TestCase):
    def test_light_accent_gets_dark_ink(self) -> None:
        self.assertEqual(_ink("#FFFFFF"), "#0C0E13")
        self.assertEqual(_ink("#2ED3B7"), "#0C0E13")

    def test_dark_accent_gets_light_ink(self) -> None:
        self.assertEqual(_ink("#000000"), "#FFFFFF")
        self.assertEqual(_ink("#7C5CFF"), "#FFFFFF")

    def test_invalid_accent_falls_back_to_default(self) -> None:
        stylesheet = build_stylesheet("not-a-color")
        self.assertIn(DEFAULT_ACCENT, stylesheet)

    def test_custom_accent_appears_in_stylesheet(self) -> None:
        stylesheet = build_stylesheet("#00A86B")
        self.assertIn("#00a86b", stylesheet.lower())


if __name__ == "__main__":
    unittest.main()
