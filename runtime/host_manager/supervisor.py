#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run one resident GPU runtime under a shared host reservation."""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import stat
import sys
import threading
import time
from pathlib import Path

try:
    from .manager import Cancelled, Capacity, Manager, Request
    from .memory import check_headroom
except ImportError:
    from manager import Cancelled, Capacity, Manager, Request
    from memory import check_headroom


def load_config(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, os.geteuid()):
            raise ValueError("Host config must be a regular file owned by root or this user")
        if info.st_mode & 0o022:
            raise ValueError("Host config must not be writable by group or others")
        config = json.load(stream)
    if set(config) != {"directory", "capacity"}:
        raise ValueError("Host config requires exactly directory and capacity")
    directory = Path(config["directory"])
    if not directory.is_absolute() or directory.is_symlink():
        raise ValueError("Host reservation directory must be an absolute non-symlink path")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.stat()
    if info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o022:
        raise ValueError("Host reservation directory must be protected and owned by root or this user")
    return directory, Capacity(**config["capacity"])


def signal_group(child, signum):
    try:
        os.killpg(child.pid, signum)
    except ProcessLookupError:
        pass


def wait_runtime(child, cancelled, grace, memory_check=None):
    stop_deadline = None
    next_memory_check = 0.0
    memory_stopped = False
    while child.poll() is None:
        if memory_check is not None and not memory_stopped and time.monotonic() >= next_memory_check:
            next_memory_check = time.monotonic() + 0.25
            try:
                memory_check()
            except (MemoryError, OSError, ValueError):
                memory_stopped = True
                print("Host memory headroom unavailable; stopping supervised workload", file=sys.stderr)
                cancelled.set()
                signal_group(child, signal.SIGTERM)
        if cancelled.is_set():
            if stop_deadline is None:
                stop_deadline = time.monotonic() + grace
            if time.monotonic() >= stop_deadline:
                signal_group(child, signal.SIGKILL)
                break
        time.sleep(0.02)
    result = child.wait()
    return 75 if memory_stopped else result if result >= 0 else 128 - result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--host-bytes", type=int, required=True)
    parser.add_argument("--gpu-bytes", type=int, required=True)
    parser.add_argument("--exclusive", action="store_true")
    parser.add_argument("--min-host-available-bytes", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--stop-grace", type=float, default=30)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a runtime command after -- is required")
    if any(not math.isfinite(v) or v < 0 for v in (args.timeout, args.stop_grace)):
        parser.error("timeout and stop-grace must be finite and nonnegative")
    if not 0 <= args.min_host_available_bytes < 2**64:
        parser.error("host memory floor must be a nonnegative byte count")
    memory_check = (lambda: check_headroom(args.min_host_available_bytes)) if args.min_host_available_bytes else None
    cancelled = threading.Event()
    pending = []
    child = None

    def forward(signum, _frame):
        pending.append(signum)
        cancelled.set()
        if child is not None:
            signal_group(child, signum)

    old_handlers = {sig: signal.signal(sig, forward) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        directory, capacity = load_config(args.config)
        deadline = time.monotonic() + args.timeout
        manager = Manager(directory, capacity, timeout=args.timeout, cancel=cancelled)
        with manager.acquire(
            Request(args.host_bytes, args.gpu_bytes, args.exclusive),
            owner=args.owner,
            timeout=max(0, deadline - time.monotonic()),
            cancel=cancelled,
        ) as lease:
            if cancelled.is_set():
                raise Cancelled()
            if memory_check is not None:
                memory_check()
            child = lease.spawn(command, start_new_session=True)
            # A signal can arrive between the cancellation check and Popen.
            if pending:
                forward(pending[-1], None)
            return wait_runtime(child, cancelled, args.stop_grace, memory_check)
    except Cancelled:
        return 128 + (pending[-1] if pending else signal.SIGTERM)
    except MemoryError:
        print("Insufficient host memory headroom for workload", file=sys.stderr)
        return 75
    except TimeoutError:
        print("GPU resource admission timed out", file=sys.stderr)
        return 75
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        print("Invalid or inconsistent host resource configuration", file=sys.stderr)
        return 64
    except OSError:
        print("Host resource or runtime launch failed", file=sys.stderr)
        return 126
    finally:
        # Unexpected exceptions must not relinquish admission while the direct
        # runtime child still runs. Inherited lock ownership is a second fence.
        if child is not None and child.poll() is None:
            signal_group(child, signal.SIGKILL)
            child.wait()
        for sig, previous in old_handlers.items():
            signal.signal(sig, previous)


if __name__ == "__main__":
    sys.exit(main())
