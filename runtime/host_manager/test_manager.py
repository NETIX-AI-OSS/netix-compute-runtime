# SPDX-License-Identifier: Apache-2.0
import fcntl
import multiprocessing as mp
import os
import signal
import sys
import tempfile
import threading
import time
import unittest

from manager import Cancelled, Capacity, Manager, Request


def hold(directory, ready):
    manager = Manager(directory, Capacity(100, 80, True))
    with manager.acquire(Request(10, 70), owner="vision"):
        ready.send("held")
        ready.recv()


def hold_with_gpu_child(directory, ready):
    manager = Manager(directory, Capacity(100, 80, True))
    with manager.acquire(Request(10, 70), owner="vision") as lease:
        child = lease.spawn([sys.executable, "-c", "import time; time.sleep(60)"])
        ready.send(child.pid)
        ready.recv()
        child.terminate()
        child.wait()


class ManagerTests(unittest.TestCase):
    def test_integrated_is_not_additional_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = Manager(directory, Capacity(100, 80, True))
            with self.assertRaises(ValueError):
                manager.acquire(Request(40, 70), owner="too-big")
            with manager.acquire(Request(10, 70), owner="foundry"):
                with self.assertRaises(TimeoutError):
                    manager.acquire(Request(21, 0), owner="vision")
                with manager.acquire(Request(20, 0), owner="small"):
                    self.assertEqual(len(manager.snapshot()), 2)
            self.assertEqual(manager.snapshot(), [])

    def test_discrete_and_exclusivity(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = Manager(directory, Capacity(100, 80, False))
            with manager.acquire(Request(90, 70), owner="foundry"):
                with self.assertRaises(TimeoutError):
                    manager.acquire(Request(0, 0, True), owner="training")
            with manager.acquire(Request(0, 0, True), owner="training"):
                with self.assertRaises(TimeoutError):
                    manager.acquire(Request(0, 1), owner="vision")

    def test_process_death_releases_kernel_fenced_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            ctx = mp.get_context("spawn")
            parent, child = ctx.Pipe()
            process = ctx.Process(target=hold, args=(directory, child))
            process.start()
            try:
                self.assertTrue(parent.poll(5))
                self.assertEqual(parent.recv(), "held")
                manager = Manager(directory, Capacity(100, 80, True))
                with self.assertRaises(TimeoutError):
                    manager.acquire(Request(0, 20), owner="other", timeout=0.1)
                process.kill()
                process.join(5)
                with manager.acquire(Request(0, 80), owner="replacement", timeout=1):
                    self.assertEqual(len(manager.snapshot()), 1)
            finally:
                if process.is_alive():
                    process.kill()
                process.join()

    def test_gpu_child_keeps_lease_after_parent_death(self):
        with tempfile.TemporaryDirectory() as directory:
            ctx = mp.get_context("spawn")
            parent, channel = ctx.Pipe()
            process = ctx.Process(target=hold_with_gpu_child, args=(directory, channel))
            process.start()
            child_pid = None
            try:
                self.assertTrue(parent.poll(5))
                child_pid = parent.recv()
                process.kill()
                process.join(5)
                manager = Manager(directory, Capacity(100, 80, True))
                with self.assertRaises(TimeoutError):
                    manager.acquire(Request(0, 20), owner="contender", timeout=0.1)
                os.kill(child_pid, signal.SIGKILL)
                with manager.acquire(Request(0, 80), owner="replacement", timeout=2):
                    self.assertEqual(len(manager.snapshot()), 1)
            finally:
                if process.is_alive():
                    process.kill()
                process.join()
                if child_pid is not None:
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_cancellation_while_waiting(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = Manager(directory, Capacity(100, 80, True))
            event = threading.Event()
            timer = threading.Timer(0.1, event.set)
            with manager.acquire(Request(0, 80), owner="held"):
                timer.start()
                try:
                    with self.assertRaises(Cancelled):
                        manager.acquire(Request(0, 1), owner="waiting", timeout=5, cancel=event)
                finally:
                    timer.join()

    def test_admission_mutex_respects_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = Manager(directory, Capacity(100, 80, True))
            fd = os.open(os.path.join(directory, "admission.lock"), os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                started = time.monotonic()
                with self.assertRaises(TimeoutError):
                    manager.acquire(Request(0, 1), owner="waiting", timeout=0.1)
                self.assertLess(time.monotonic() - started, 1)
            finally:
                os.close(fd)

    @unittest.skipUnless(hasattr(os, "fork"), "Unix fork test")
    def test_fork_child_cannot_release_parent_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = Manager(directory, Capacity(100, 80, True))
            with manager.acquire(Request(0, 80), owner="parent") as lease:
                pid = os.fork()
                if pid == 0:
                    try:
                        lease.close()
                    except RuntimeError:
                        os._exit(0)
                    os._exit(1)
                _, status = os.waitpid(pid, 0)
                self.assertEqual(status, 0)
                with self.assertRaises(TimeoutError):
                    manager.acquire(Request(0, 1), owner="contender")

    def test_exception_release_cancel_and_config_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = Manager(directory, Capacity(100, 80, True))
            with self.assertRaises(RuntimeError):
                with manager.acquire(Request(0, 80), owner="failing"):
                    raise RuntimeError("inference failure")
            self.assertEqual(manager.snapshot(), [])
            event = threading.Event()
            event.set()
            with self.assertRaises(Cancelled):
                manager.acquire(Request(0, 80), owner="cancelled", cancel=event)
            with self.assertRaises(ValueError):
                Manager(directory, Capacity(200, 80, True))


if __name__ == "__main__":
    unittest.main()
