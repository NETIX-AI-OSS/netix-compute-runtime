# SPDX-License-Identifier: Apache-2.0
"""Cross-process, kernel-fenced resource reservations for a single Linux host.

Every GPU consumer must use the same trusted local directory and capacity config.
Locks must remain held until the actual GPU process/model residency has ended.
"""

from __future__ import annotations

import contextlib
import dataclasses
import fcntl
import json
import math
import os
import subprocess
import threading
import time
import uuid
import weakref
from pathlib import Path

_LEASES = weakref.WeakSet()


def _close_inherited_leases():
    for lease in list(_LEASES):
        lease._after_fork()


os.register_at_fork(after_in_child=_close_inherited_leases)


@dataclasses.dataclass(frozen=True)
class Capacity:
    system_bytes: int
    gpu_bytes: int
    integrated: bool

    def __post_init__(self):
        for value in (self.system_bytes, self.gpu_bytes):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError("Capacities must be positive integer bytes")
        if not isinstance(self.integrated, bool):
            raise ValueError("integrated must be boolean")


@dataclasses.dataclass(frozen=True)
class Request:
    host_bytes: int
    gpu_bytes: int
    exclusive: bool = False

    def __post_init__(self):
        for value in (self.host_bytes, self.gpu_bytes):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("Reservations must be nonnegative integer bytes")
        if not isinstance(self.exclusive, bool):
            raise ValueError("exclusive must be boolean")


class Cancelled(Exception):
    """Admission was cancelled before resources were granted."""


class Lease:
    def __init__(self, fd: int, token: str):
        self.fd = fd
        self.token = token
        self.pid = os.getpid()
        # Fork children must not keep a dead parent's lease alive. Closing (not
        # LOCK_UN) preserves the parent's shared open-file-description lock.
        _LEASES.add(self)

    def _after_fork(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def close(self):
        if os.getpid() != self.pid:
            raise RuntimeError("Only the acquiring process can release its lease")
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def spawn(self, args, **kwargs):
        """Launch the GPU process with inherited kernel lease ownership.

        The child must retain its inherited descriptors until exit. Shell wrappers
        that daemonize or close arbitrary descriptors are not supported.
        """
        if self.pid != os.getpid() or self.fd is None:
            raise RuntimeError("A live owning lease is required to launch a process")
        if "pass_fds" in kwargs or "close_fds" in kwargs or kwargs.get("shell"):
            raise ValueError("Lease controls descriptor inheritance; shell is unsupported")
        # A separate descriptor avoids the Python at-fork hook closing the
        # descriptor explicitly passed to the executable by Popen.
        inherited = os.dup(self.fd)
        try:
            return subprocess.Popen(args, pass_fds=(inherited,), **kwargs)
        finally:
            os.close(inherited)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Manager:
    def __init__(
        self,
        directory: str | Path,
        capacity: Capacity,
        *,
        timeout: float | None = None,
        cancel: threading.Event | None = None,
    ):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.capacity = capacity
        if timeout is not None and (not math.isfinite(timeout) or timeout < 0):
            raise ValueError("timeout must be finite and nonnegative")
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._guard(deadline, cancel):
            config = self.directory / "capacity.json"
            expected = dataclasses.asdict(capacity)
            if config.exists():
                if json.loads(config.read_text()) != expected:
                    raise ValueError("All consumers must use identical host capacity")
            else:
                temp = self.directory / "capacity.tmp"
                temp.write_text(json.dumps(expected))
                temp.replace(config)

    @contextlib.contextmanager
    def _guard(self, deadline=None, cancel=None):
        fd = os.open(self.directory / "admission.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled("Resource admission cancelled")
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if deadline is not None and time.monotonic() >= deadline:
                        raise TimeoutError("Host admission lock is occupied") from None
                    time.sleep(0.01)
            yield
        finally:
            os.close(fd)

    def _live(self):
        records = []
        for path in self.directory.glob("lease-*.json"):
            fd = os.open(path, os.O_RDWR)
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    # Only lock ownership proves liveness, never PID or time.
                    records.append(json.loads(path.read_text()))
                else:
                    path.unlink()  # serialized with every new lease creation
            finally:
                os.close(fd)
        return records

    def _fits(self, requests):
        host = sum(r.host_bytes for r in requests)
        gpu = sum(r.gpu_bytes for r in requests)
        system = host + gpu if self.capacity.integrated else host
        return system <= self.capacity.system_bytes and gpu <= self.capacity.gpu_bytes

    def acquire(
        self, request: Request, *, owner: str, timeout: float = 0, cancel: threading.Event | None = None
    ) -> Lease:
        if not owner or not isinstance(owner, str):
            raise ValueError("owner must be a nonempty string")
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be finite and nonnegative")
        if not self._fits([request]):
            raise ValueError("Request exceeds host capacity")
        deadline = time.monotonic() + timeout
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled("Resource admission cancelled")
            with self._guard(deadline, cancel):
                live = self._live()
                requests = [Request(**record["request"]) for record in live]
                conflict = requests and (request.exclusive or any(r.exclusive for r in requests))
                if not conflict and self._fits([*requests, request]):
                    token = uuid.uuid4().hex
                    path = self.directory / f"lease-{token}.json"
                    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        record = {
                            "token": token,
                            "owner": owner,
                            "pid": os.getpid(),
                            "request": dataclasses.asdict(request),
                        }
                        os.write(fd, json.dumps(record).encode())
                        return Lease(fd, token)
                    except BaseException:
                        os.close(fd)
                        path.unlink(missing_ok=True)
                        raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Host resources are occupied")
            if cancel is not None:
                cancel.wait(min(remaining, 0.05))
            else:
                time.sleep(min(remaining, 0.05))

    def snapshot(self):
        with self._guard():
            return self._live()
