# Shared host resource admission

This Python standard-library component coordinates cooperative GPU consumers on
one Linux host. It is a primitive, not yet an integrated service or fleet feature.
Run tests with `python3 -m unittest discover -s runtime/host_manager -v`.

Provision one protected local-filesystem directory shared by the Foundry and
Vision runtime processes, and one **identical** capacity configuration. Never use
NFS or a per-container private directory. Capacity is allocatable memory **after**
OS, gateway and operational reserves; reported device limits are not automatically
free memory. Integrated GPU allocations consume both the GPU budget and system
memory budget. Discrete GPU allocations consume the device budget separately.
`host_bytes` excludes bytes already counted as GPU allocations. Backend selection
(Vulkan, CUDA) does not change physical accounting.

```python
manager = Manager(
    "/run/netix/gpu-admission/device-0",
    Capacity(system_bytes=12_000_000_000, gpu_bytes=12_000_000_000, integrated=True),
)
with manager.acquire(
    Request(host_bytes=1_000_000_000, gpu_bytes=8_000_000_000), owner="vision:job-uuid", timeout=60, cancel=cancel_event
):
    # Load, execute and fully unload the model before exiting this scope.
    execute_and_unload()
```

Reservations are held by kernel file locks, not heartbeat timestamps or PID
checks. A new manager instance cannot steal an existing reservation. Process
termination releases its lock, and the next admission removes stale metadata.
UUID tokens distinguish separate reservations. Fork children close inherited
handles without unlocking the parent's lock. Admission and metadata scanning are
serialized, including recovery. Invalid/different capacity configurations fail
closed. Cancellation applies to waiting admission; exceptions release an acquired
lease through its context manager. The queue is bounded by caller timeout but is
**not FIFO** and provides no fairness guarantee.

## Required integration

- Foundry's model server cache must hold the lease for **model residency**, not
  just for the HTTP request. Release after server exit/unload is verified.
- Vision's VLM and training engines must obtain the same host lease before model
  allocation. A training job reserves checkpoint/optimizer/activation peaks and
  can request exclusive ownership. Cancellation must stop GPU execution before
  releasing ownership; checkpoint/preemption logic belongs to the engine.
- Supervise GPU subprocesses in the same process-lifetime group/cgroup. A dead
  Python parent cannot prove a surviving external GPU server stopped. The lease
  owner must be the GPU execution process or a supervisor with enforced child
  teardown. Use `lease.spawn([executable, ...])` to pass kernel ownership to the
  actual GPU subprocess: if the parent dies, the reservation remains held until
  that child exits. This is tested with parent SIGKILL and a surviving subprocess.
  The executable must retain inherited file descriptors (no daemonization or
  close-all-FDs wrapper); deeper subprocess trees must propagate that ownership.
  This library does not kill orphan children or fence GPU writes.
- Expose `snapshot()` through the authenticated fleet agent, never by publishing
  the local directory or making it world-writable. Directory permissions and
  trusted clients are part of the boundary; this is not a hostile-client quota
  system. Estimates require workload measurement and OOM headroom.
- Resource admission must happen before job claim, or unsuccessful admission must
  use a real queue release/retry contract; do not strand claimed jobs.
- This initial component models one physical accelerator; multi-GPU atomic bundle
  admission requires a host-level inventory and combined transaction.

No workload is marked supported merely because it can acquire a lease. Model
backend capability and quality validation remain separate requirements.

## Supervisor CLI

Both services can wrap their **resident model process** with the same supervisor:

```sh
python /opt/netix/host_manager/supervisor.py \
  --config /etc/netix/host-resources.json \
  --owner foundry:model-digest \
  --host-bytes 1000000000 --gpu-bytes 8000000000 \
  --timeout 60 --stop-grace 30 -- /opt/llama/llama-server --model /models/model.gguf
```

The config contains exactly:

```json
{"directory":"/run/netix/gpu-admission/device-0","capacity":{"system_bytes":12000000000,"gpu_bytes":12000000000,"integrated":true}}
```

The config must be a non-symlink regular file owned by root or the execution user
and must not be writable by group/others. The reservation directory has equivalent
ownership/write restrictions. Deployment must also protect the parent directories
against replacement. This CLI performs no elevation and prints no config contents,
command arguments, or environment values. Child stdout/stderr pass through normally;
the underlying application remains responsible for redacting its own logs.

`--exclusive` reserves sole use. `--timeout` bounds admission, including the initial
configuration mutex; timeout exits 75. SIGTERM/SIGINT cancel queued admission (143 /
130) or forward to the runtime process group. The supervisor waits for the runtime
exit, escalating to SIGKILL after `--stop-grace`; it never releases its reservation
while a direct child remains alive. The child additionally inherits the kernel
lease. Normal child exit codes propagate unchanged; signal death returns 128 plus
the signal number. Invalid config exits 64; launch/filesystem failures exit 126.

Use a directly executed runtime that retains inherited descriptors. Avoid shell
wrappers, daemonization and self-detaching services. Process-group forwarding helps
stop runtime children; child trees must retain the lease descriptor or be enclosed
in an independently enforced cgroup lifecycle. Cancellation of training should
checkpoint inside the runtime signal handler within the configured grace period.
The supervisor does not manufacture a checkpoint or impose a job execution timeout.
