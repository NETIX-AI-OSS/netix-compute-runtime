# SPDX-License-Identifier: Apache-2.0
# Resource lifetimes span setUp/tearDown or require kill-before-wait cleanup.
# pylint: disable=consider-using-with
import json
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from manager import Capacity, Manager, Request

SCRIPT = str(Path(__file__).with_name("supervisor.py"))


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.directory = self.root / "leases"
        self.config = self.root / "config.json"
        self.config.write_text(
            json.dumps(
                {
                    "directory": str(self.directory),
                    "capacity": {"system_bytes": 100, "gpu_bytes": 80, "integrated": True},
                }
            )
        )
        self.config.chmod(0o600)

    def tearDown(self):
        self.temp.cleanup()

    def command(self, program, *extra):
        return [
            sys.executable,
            SCRIPT,
            "--config",
            str(self.config),
            "--owner",
            "test",
            "--host-bytes",
            "10",
            "--gpu-bytes",
            "70",
            *extra,
            "--",
            sys.executable,
            "-c",
            program,
        ]

    def wait_file(self, name):
        deadline = time.monotonic() + 5
        while not (self.root / name).exists():
            if time.monotonic() > deadline:
                self.fail("runtime did not reach expected state")
            time.sleep(0.02)

    def test_exit_code_and_protected_config(self):
        result = subprocess.run(self.command("raise SystemExit(19)"), timeout=5, check=False)
        self.assertEqual(result.returncode, 19)
        self.assertEqual(Manager(self.directory, Capacity(100, 80, True)).snapshot(), [])
        self.config.chmod(0o666)
        result = subprocess.run(self.command("raise SystemExit(19)"), timeout=5, check=False, capture_output=True)
        self.assertEqual(result.returncode, 64)
        self.assertNotIn(str(self.root).encode(), result.stderr)

    def test_signal_waits_for_runtime_cleanup_and_retains_reservation(self):
        program = f"""import signal,time
from pathlib import Path
root=Path({str(self.root)!r})
def stop(sig, frame):
    (root/'stopping').touch()
    time.sleep(0.5)
    (root/'cleaned').touch()
    raise SystemExit(23)
signal.signal(signal.SIGTERM, stop)
(root/'ready').touch()
while True: time.sleep(0.1)
"""
        process = subprocess.Popen(self.command(program))
        try:
            self.wait_file("ready")
            process.send_signal(signal.SIGTERM)
            self.wait_file("stopping")
            manager = Manager(self.directory, Capacity(100, 80, True))
            with self.assertRaises(TimeoutError):
                manager.acquire(Request(0, 20), owner="contender")
            self.assertIsNone(process.poll())
            self.assertEqual(process.wait(5), 23)
            self.assertTrue((self.root / "cleaned").exists())
            with manager.acquire(Request(0, 80), owner="next", timeout=1):
                pass
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()

    def test_sigint_cancels_waiting_admission(self):
        manager = Manager(self.directory, Capacity(100, 80, True))
        with manager.acquire(Request(0, 80), owner="held"):
            process = subprocess.Popen(self.command("raise SystemExit(19)"))
            try:
                time.sleep(0.2)
                process.send_signal(signal.SIGINT)
                self.assertEqual(process.wait(5), 130)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()

    def test_forces_child_exit_after_grace_and_propagates_signal_status(self):
        program = f"""import signal,time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path({str(self.root / "ready")!r}).touch()
while True: time.sleep(0.1)
"""
        process = subprocess.Popen(self.command(program, "--stop-grace", "0.1"))
        try:
            self.wait_file("ready")
            process.terminate()
            self.assertEqual(process.wait(5), 137)
            manager = Manager(self.directory, Capacity(100, 80, True))
            self.assertEqual(manager.snapshot(), [])
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()

    def test_admission_timeout_has_distinct_status(self):
        manager = Manager(self.directory, Capacity(100, 80, True))
        with manager.acquire(Request(0, 80), owner="held"):
            result = subprocess.run(
                self.command("raise SystemExit(19)", "--timeout", "0.1"), capture_output=True, timeout=5, check=False
            )
            self.assertEqual(result.returncode, 75)


if __name__ == "__main__":
    unittest.main()
