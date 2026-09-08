# Supported platforms and qualification

| Component | Coverage |
| --- | --- |
| Admission locks and supervisor | Linux; Python 3.11–3.14 CI |
| Process wait/cancellation | Python standard library |
| Vulkan device probe | Linux Vulkan loader; enumerates physical devices and memory metadata |
| Public base image | Linux amd64 initially |
| Models and training | Client plugins; no model capabilities advertised by this library |

GPU availability does not establish workload support. Clients qualify the exact vendor/device/driver, model, precision and resource envelope before scheduling. AMD, Intel and NVIDIA quality/performance parity is not claimed. macOS and ARM image qualification remain explicit follow-up work. Latency and task accuracy are client metrics; no 67% accuracy claim is made here.
