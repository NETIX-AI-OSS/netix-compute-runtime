# SPDX-License-Identifier: Apache-2.0
"""Linux host-memory headroom checks for supervised GPU workloads."""

from pathlib import Path


def available_bytes(path=Path("/proc/meminfo")):
    """Read kernel-estimated available RAM; never substitute MemFree or swap."""
    with Path(path).open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("Oversized host memory report")
    matches = [line.split() for line in raw.splitlines() if line.startswith(b"MemAvailable:")]
    if len(matches) != 1:
        raise ValueError("Host memory availability is missing or ambiguous")
    fields = matches[0]
    if len(fields) != 3 or fields[2] != b"kB" or not fields[1].isdigit():
        raise ValueError("Invalid host memory availability")
    value = int(fields[1]) * 1024
    if value >= 2**64:
        raise ValueError("Host memory availability overflow")
    return value


def check_headroom(minimum, path=Path("/proc/meminfo")):
    if (not isinstance(minimum, int) or isinstance(minimum, bool)) or not 0 < minimum < 2**64:
        raise ValueError("Host memory floor must be a positive byte count")
    if available_bytes(path) < minimum:
        raise MemoryError("Host memory headroom fell below the configured floor")
