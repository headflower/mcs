from __future__ import annotations

import unittest

from mcs.core.tasks import TaskHandle, TaskRunner


class TaskMuteTest(unittest.TestCase):
    def test_queued_progress_is_dropped_after_mute(self) -> None:
        pending = []
        calls = []
        handle = TaskHandle(dispatch=pending.append)
        handle.on_progress = lambda done, total, message: calls.append((done, total, message))
        handle.on_status = lambda message: calls.append(message)
        handle.progress(1, 2, "half")
        handle.status("working")
        handle.mute()
        for callback in pending:
            callback()
        self.assertEqual(calls, [])
        self.assertTrue(handle.cancelled)
        self.assertTrue(handle.muted)

    def test_done_callback_runs_and_handle_finishes(self) -> None:
        pending = []
        results = []
        runner = TaskRunner(dispatch=pending.append)
        handle = runner.run(lambda task: 42, title="unit", on_done=results.append)
        for _ in range(100):
            if handle.done:
                break
            import time

            time.sleep(0.01)
        for callback in pending:
            callback()
        self.assertTrue(handle.done)
        self.assertEqual(results, [42])


if __name__ == "__main__":
    unittest.main()
