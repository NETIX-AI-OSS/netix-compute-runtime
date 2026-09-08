# Integrating a client worker

Keep job definitions, models, datasets and training/inference code in the client
repository. Install this package into that client's worker image, or extend its
verified base image. Both approaches expose the same supervisor and Python APIs.

## Configure one shared admission domain

Provision a protected local directory and JSON configuration on the worker host.
Every cooperating process must use that same directory and identical capacity.
Containers must bind-mount the host directory; separate container directories
cannot coordinate reservations. Use a common trusted execution identity with
write access. Do not make the directory group/world writable to share it.

Example `/etc/netix/host-resources.json`:

```json
{
  "directory": "/run/netix/gpu-admission/device-0",
  "capacity": {
    "system_bytes": 12000000000,
    "gpu_bytes": 12000000000,
    "integrated": true
  }
}
```

These numbers illustrate an allocatable budget after operating-system and other
service reserves; measure and set them for the actual host. The supervisor requires
an absolute, non-symlink reservation path and a regular, non-symlink config file.
Both must be owned by root or the execution user and not writable by group/others.
Protect parent directories against replacement as well.

## Launch the client's executable

```sh
netix-runtime-supervisor \
  --config /etc/netix/host-resources.json \
  --owner client:job-123 \
  --host-bytes 1000000000 --gpu-bytes 8000000000 \
  --min-host-available-bytes 2000000000 \
  --timeout 60 --stop-grace 30 \
  -- /opt/client/bin/run-job
```

`run-job` is provided by the client. Pass an argument vector directly after `--`;
there is no shell expansion. Keep its lease for the entire model residency,
including checkpoint writes and unloading. The executable must retain inherited
file descriptors. Avoid daemonization and wrappers that close arbitrary descriptors.
Use an independently enforced cgroup lifecycle for child trees that cannot retain
the lease descriptor.

Admission waits at most `--timeout`; this is **not** an execution time limit.
The optional memory floor checks Linux `MemAvailable` before launch and periodically
while running. Falling below it stops the process group and returns 75. It is not a
GPU-memory or cgroup-limit monitor. SIGTERM/SIGINT are forwarded to the child process
group; teardown escalates after `--stop-grace`. Checkpoint handling remains the
client executable's responsibility.

Claim a job only after admission, or use a queue contract that returns/retries the
job if admission fails. A client decides whether and when to retry exit 75, reports
results, and schedules further work. See [exit codes and lease rules](../runtime/host_manager/README.md).

## Container integration

The public Linux amd64 image is
`ghcr.io/netix-ai-oss/netix-compute-runtime`. Select the digest from a successful
release workflow's image summary, verify its source commit, then record that
immutable digest in the client's dependency configuration:

```sh
# Set these to the selected release image digest and reviewed source commit.
IMAGE_DIGEST=sha256:REPLACE_WITH_VERIFIED_DIGEST
SOURCE_COMMIT=REPLACE_WITH_REVIEWED_COMMIT
gh attestation verify "oci://ghcr.io/netix-ai-oss/netix-compute-runtime@$IMAGE_DIGEST" \
  --repo NETIX-AI-OSS/netix-compute-runtime --source-digest "$SOURCE_COMMIT" \
  --signer-workflow NETIX-AI-OSS/netix-compute-runtime/.github/workflows/runtime.yml
```

Extend the pinned base with client dependencies and executables. Its default
entrypoint is `netix-runtime-supervisor` and its default user is UID/GID 1000.
Mount the shared reservation directory read-write, the host config read-only, and
provide the accelerator devices and drivers needed by the client's selected
backend. The base supplies no CUDA engine or model libraries. Keep credentials and
client data in runtime mounts or the client's secret/data delivery system.

The image contains `netix-vulkan-device-probe --memory`; the wheel does not.
The probe reports physical device identity and heap sizes. Its `available_bytes`
is null: heap capacity is not measured free memory. Clients select and qualify
devices before deriving admission budgets.

## Python interfaces

Prefer the supervisor for external executables. In-process clients can use the
lease API, provided they unload resources before leaving the context:

```python
from runtime.host_manager.manager import Capacity, Manager, Request

manager = Manager(
    "/run/netix/gpu-admission/device-0",
    Capacity(system_bytes=12_000_000_000, gpu_bytes=12_000_000_000, integrated=True),
    timeout=60,
)
with manager.acquire(
    Request(host_bytes=1_000_000_000, gpu_bytes=8_000_000_000),
    owner="client:job-123",
    timeout=60,
) as lease:
    # Pass ownership to a directly executed child and wait for full exit.
    child = lease.spawn(["/opt/client/bin/run-job"])
    child.wait()
```

The low-level API expects a trusted, correctly provisioned directory; it does not
apply the CLI's configuration-file checks. `lease.spawn` preserves the reservation
if the Python parent dies while its child survives; it does not automatically kill
that child. For signal forwarding and teardown, use the supervisor instead.

`netix_compute_runtime.process.wait_process(process, timeout, cancelled=None)`
adds a bounded, cancellable wait. It raises `subprocess.TimeoutExpired` or
`RuntimeCancelled`; **the caller must terminate and reap the process on exceptions**.
It neither acquires a lease nor supervises a process tree.
