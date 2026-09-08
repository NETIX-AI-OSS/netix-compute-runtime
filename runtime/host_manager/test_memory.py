# SPDX-License-Identifier: Apache-2.0
import tempfile
import unittest
from pathlib import Path

try:
    from .memory import available_bytes, check_headroom
except ImportError:
    from memory import available_bytes, check_headroom


class MemoryTests(unittest.TestCase):
    def test_uses_available_not_free_or_swap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "meminfo"
            path.write_text("MemFree: 1 kB\nMemAvailable: 4096 kB\nSwapFree: 999999 kB\n")
            self.assertEqual(available_bytes(path), 4194304)
            check_headroom(4194304, path)
            with self.assertRaises(MemoryError):
                check_headroom(4194305, path)

    def test_invalid_reports_cannot_claim_headroom(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "meminfo"
            for raw in [
                "MemFree: 100 kB",
                "MemAvailable: -1 kB",
                "MemAvailable: 1 MB",
                "MemAvailable: 1 kB\nMemAvailable: 2 kB",
                "x" * 65537,
            ]:
                with self.subTest(raw=raw[:40]):
                    path.write_text(raw)
                    with self.assertRaises(ValueError):
                        available_bytes(path)


class RuntimeMemoryTests(unittest.TestCase):
    def test_memory_pressure_stops_and_reaps_owned_child(self):
        import subprocess
        import sys
        import threading

        try:
            from .supervisor import wait_runtime
        except ImportError:
            from supervisor import wait_runtime

        # Explicit finally cleanup verifies that the supervisor itself reaps the child.
        # pylint: disable=consider-using-with
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        checks = []

        def headroom():
            checks.append(True)
            if len(checks) == 2:
                raise MemoryError("test pressure")

        try:
            self.assertEqual(wait_runtime(child, threading.Event(), 0.1, headroom), 75)
            self.assertIsNotNone(child.poll())
            self.assertEqual(len(checks), 2)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
