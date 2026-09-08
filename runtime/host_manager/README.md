# Host admission reference

For setup and runnable interfaces, start with the [integration guide](../../docs/INTEGRATION.md).
This standard-library component coordinates trusted consumers of one physical
accelerator on a Linux host. Vulkan and CUDA consumers must share the same
admission directory and capacity configuration to coordinate physical resources.

## Resource accounting

- Capacity is an allocatable budget after OS, gateway and operational reserves.
  Hardware heap size is not free memory; clients estimate workload peaks and OOM
  headroom, including optimizer state, activations and checkpoints.
- `Request.host_bytes` excludes the bytes declared in `gpu_bytes`. For integrated
  GPUs, host plus GPU reservations consume the system budget; GPU reservations
  also consume the GPU budget. For discrete GPUs, the two budgets are separate.
- An exclusive request cannot coexist with any other reservation. A request larger
  than capacity, or a capacity configuration different from existing consumers,
  fails closed.
- Admission is bounded by caller timeout and supports cancellation. The queue is
  not FIFO and has no fairness guarantee. It performs no multi-GPU atomic admission.

## Lease lifetime

Kernel file locks establish reservation liveness; timestamps and PID checks do
not. Admission and stale-metadata removal are serialized. Each reservation has a
UUID. A new manager cannot steal an existing live reservation. When the last lock
holder exits, a later admission removes stale metadata.

A lease must span **model residency**, not just an API request. Its context manager
releases the owning handle on exit or exception. Fork children close inherited
handles without unlocking their parent's reservation. `lease.spawn` explicitly
passes lock ownership to an executable so a surviving child retains the reservation
after its parent's death. That executable must retain inherited descriptors;
deeper process trees must propagate ownership or have an enforced cgroup lifecycle.

The library does not fence GPU writes, stop noncooperating consumers, or kill
orphans after supervisor SIGKILL. The CLI forwards ordinary cancellation to the
process group and waits for the direct child before releasing its own handle.
These are cooperative lifecycle guarantees, not a hostile-client quota system.

`snapshot()` reports active reservation metadata. If a client exposes it remotely,
use its authenticated agent API. Never expose the local directory or make it
world-writable.

## Supervisor exit codes

| Exit | Meaning |
| --- | --- |
| Child's exit code | Normal workload completion or failure |
| 128 + signal | Child terminated by signal, or cancellation during admission |
| 75 | Admission timeout or insufficient monitored host memory headroom |
| 64 | Invalid/inconsistent configuration or resource request |
| 126 | Filesystem or process launch failure |
| 2 | Invalid command-line arguments |

SIGTERM/SIGINT during admission produce 143/130. While executing, signals are
forwarded and the actual child result propagates; a client handler may exit cleanly.
Memory-pressure stops return 75 regardless of the child's cleanup result. Memory
report read errors before launch follow the configuration/filesystem error paths;
during execution they stop the workload and return 75.

`--timeout` bounds admission, including the configuration mutex. `--stop-grace`
bounds graceful teardown before SIGKILL. Neither limits total execution time.
The CLI prints no command arguments, environment values or config contents;
child stdout/stderr pass through and require client-side redaction.
