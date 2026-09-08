FROM debian:bookworm-slim AS probe
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev libvulkan-dev && rm -rf /var/lib/apt/lists/*
COPY native/device_probe.c /build/device_probe.c
RUN gcc -Wall -Wextra -Werror /build/device_probe.c -lvulkan -o /build/netix-vulkan-device-probe

FROM python:3.14-slim-bookworm
LABEL org.opencontainers.image.source="https://github.com/NETIX-AI-OSS/netix-compute-runtime"
LABEL org.opencontainers.image.licenses="Apache-2.0"
RUN apt-get update && apt-get install -y --no-install-recommends libvulkan1 mesa-vulkan-drivers ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=probe /build/netix-vulkan-device-probe /usr/local/bin/netix-vulkan-device-probe
WORKDIR /opt/netix
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY netix_compute_runtime ./netix_compute_runtime
COPY runtime/host_manager ./runtime/host_manager
RUN pip wheel --no-deps --wheel-dir /opt/netix/dist . && pip install --no-deps /opt/netix/dist/*.whl && rm -rf netix_compute_runtime runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
ENTRYPOINT ["netix-runtime-supervisor"]
CMD ["--help"]
