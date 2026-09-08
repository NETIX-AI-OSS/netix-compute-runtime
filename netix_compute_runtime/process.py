# SPDX-License-Identifier: Apache-2.0
"""Bounded waits for supervised runtime processes with cooperative cancellation."""

import subprocess
import time


class RuntimeCancelled(RuntimeError):
    """The owning job cancelled execution; no result may be published."""


def check_cancelled(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise RuntimeCancelled("Runtime execution cancelled")


def wait_process(process, timeout, cancelled=None):
    """Caller retains process ownership and must terminate/reap on exceptions."""
    deadline = time.monotonic() + timeout
    while True:
        check_cancelled(cancelled)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            code = process.wait(timeout=min(0.1, remaining))
        except subprocess.TimeoutExpired:
            continue
        check_cancelled(cancelled)
        return code
