# NETIX Compute Runtime

Apache-2.0, model-independent worker infrastructure for client-owned workloads.

The library owns device discovery, cooperative host/GPU memory admission, process supervision, cancellation and process-lifetime cleanup. It does not own models, model architectures, checkpoints, datasets, reward functions, prompts, feature logic or tenant credentials. Those remain in client implementations and their worker images.

## Install

Use Python 3.11 or newer on Linux (macOS supports the portable process primitives).
Download the wheel from a GitHub release and verify its GitHub attestation before installation. The public OCI base is `ghcr.io/netix-ai-oss/netix-compute-runtime`; consumers must pin a verified digest rather than a mutable tag.

```sh
python -m pip install ./netix_compute_runtime-0.1.0-py3-none-any.whl
netix-runtime-supervisor --help
```

Existing `runtime.host_manager` imports remain compatible. New clients can use `netix_compute_runtime.process` for bounded process waits and cancellation. All Python runtime code uses the standard library.

## Client ownership

| Public runtime | Client implementation |
| --- | --- |
| Vulkan physical device probe | Selected model, weights and architecture implementation |
| Host/GPU memory reservations | Job types, training data, prompts and rewards |
| Supervised process lifecycle | Inference/training command and preprocessing |
| Cancellation and memory-pressure stop | Results, checkpoints and task-quality evaluation |
| Versioned library and base image | Auth, tenant/site configuration and fleet promotion |

A client extends the pinned base image with its own executable, model dependencies and business logic. It passes that executable to the supervisor as an argument vector after `--`; the supervisor does not use a shell or interpret a model/dataset schema. Secrets and data are supplied at deployment/run time, never committed or baked into the public base.

See [host admission](runtime/host_manager/README.md), [supported platforms](docs/SUPPORTED_PLATFORMS.md), [public release audit](docs/PUBLIC_RELEASE_AUDIT.md) and [third-party notices](THIRD_PARTY_NOTICES.md).

## Development

```sh
python -m unittest discover -s runtime/host_manager -p 'test_*.py'
python -m unittest discover -s tests
python -m pip wheel --no-deps --wheel-dir dist .
```

CI uses GitHub-hosted runners, scans secrets, tests the installed wheel, and builds a model-free image. Main/tag builds publish signed public artifacts. No workflow deploys to customer devices or automatically promotes a fleet. The runtime does not imply any model's accuracy or hardware qualification.
