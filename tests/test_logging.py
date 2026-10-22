from __future__ import annotations

import logging
import unittest

from mcs.core.logging import MemoryLogHandler


class MemoryLogHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = MemoryLogHandler(capacity=3)

    def _emit(self, message: str) -> None:
        record = logging.LogRecord("mcs.test", logging.INFO, __file__, 1, message, (), None)
        self.handler.emit(record)

    def test_sequence_survives_buffer_rotation(self) -> None:
        for index in range(1, 6):
            self._emit(f"line-{index}")
        entries, cursor = self.handler.entries(0)
        self.assertEqual([entry.message for entry in entries], ["line-3", "line-4", "line-5"])
        self.assertEqual(cursor, 5)

        # 同一个游标再次读取不会重复，新日志会接在序列号之后。
        entries, cursor = self.handler.entries(cursor)
        self.assertEqual(entries, [])
        self._emit("line-6")
        entries, cursor = self.handler.entries(cursor)
        self.assertEqual([entry.message for entry in entries], ["line-6"])
        self.assertEqual(cursor, 6)

    def test_clear_resets_entries_but_not_sequence(self) -> None:
        self._emit("before")
        _, cursor = self.handler.entries(0)
        self.handler.clear()
        entries, _ = self.handler.entries(0)
        self.assertEqual(entries, [])
        self._emit("after")
        entries, next_cursor = self.handler.entries(cursor)
        self.assertEqual([entry.message for entry in entries], ["after"])
        self.assertEqual(next_cursor, cursor + 1)


if __name__ == "__main__":
    unittest.main()
