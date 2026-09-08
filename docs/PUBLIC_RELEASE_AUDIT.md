# Public release audit

Audit date: 2026-09-08. Scope: the initial generic runtime export, its Python wheel, native Vulkan device probe, documentation and release workflow.

## Ownership boundary

Only model-independent resource admission, process supervision, cancellation, environment parsing and device discovery are exported. Client repositories retain all model implementations and weights, training/inference pipelines, datasets, checkpoints, prompts, rewards, job types, use cases, credentials and deployment configuration. Moving execution onto a worker does not transfer ownership to this library.

The public repository starts with new history. No private repository history, operational evidence, worker configuration, model fixtures or training assets is carried into the export. The previous private implementation remains available to its clients.

## Checks and results

- Gitleaks 8.30.1 scanned all available history of the private source repository with fully redacted output. Four detections were inspected and classified as artifact/tokenizer SHA-256 checksums. Their diagnostic files are excluded from this export. No credentials were identified by that scan.
- Gitleaks scanned the public candidate directory without findings. CI repeats the scan against all public Git history.
- The built wheel installs without dependencies. Its isolated boundary test verifies generic imports and absence of Vision, Torch, Transformers, Django and Ultralytics modules. The 16 resource-management and supervision tests passed locally.
- Source and packaging review excludes model assets, training datasets, tenant configuration, private deployment evidence and vendored model-specific code. CI rejects common forbidden paths and artifact formats; this complements manual review rather than proving arbitrary files cannot contain sensitive data.
- The Python runtime has no third-party runtime dependencies. NETIX source is licensed Apache-2.0. Container OS libraries retain their own licenses and notices; see THIRD_PARTY_NOTICES.md.
- Model-specific dependencies and assets from the prior private extraction are excluded, including Ultralytics-related code, tokenizer assets, native model-training implementation and model configurations. No model or dependency license is changed by this export.
- Public PRs use GitHub-hosted runners. Artifact publication uses the repository-scoped GitHub Actions token and OIDC provenance; it requires no private repository checkout or personal access token. Workflows do not deploy or promote fleets.

## Limits

Secret scanners and source review reduce disclosure risk; they do not establish a mathematical guarantee that no sensitive content exists. This audit covers the exported source boundary, not client repositories or client images. Hardware execution, model accuracy and complete NVIDIA/Vulkan feature parity are separate client qualifications and are not claimed here. Hosted CI, published artifact provenance and anonymous artifact access must be verified after publication.
