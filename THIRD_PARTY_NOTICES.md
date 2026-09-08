# Third-party components

NETIX-owned source in this repository is Apache-2.0; LICENSE and NOTICE are included in distributions. No model code, model weights, training datasets, copied published-model configurations, OpenAI tokenizer assets, Ultralytics exporters, or internal hardware diagnostics are included.

The Python library has no runtime package dependencies. Packaging uses setuptools and wheel under their own licenses; they are build tools, not relicensed project code.

The optional OCI base includes CPython, Debian packages, the Vulkan loader and Mesa drivers. Their upstream licenses and packaged copyright notices remain applicable and are retained in the image. The image as a collection is not represented as entirely Apache-2.0. The device probe is NETIX implementation code using the Vulkan public API; SDK headers and linked libraries retain upstream terms.

Client plugins and model artifacts have separate licenses. This project grants no rights to Qwen model materials or Ultralytics packages. Clients must select and distribute their own dependencies and data under appropriate terms.
