# Build worker requirements

Linux jobs select the public-enabled runner group `e2e-worker` with `[build-only, Linux, X64]` labels. Docker image builds and Linux job containers require a working Docker CLI and daemon on the selected worker. Changing the runner group does not install Docker.

The group currently has one Linux X64 worker. Verify Docker support with a same-head CI run before merging. Do not remove test gates or change platform labels to work around missing worker capabilities.

Python audit, wheel tests and wheel release jobs also select `e2e-worker`. Image publication and wheel release guards are unchanged; a pull-request run validates image construction and isolated container smoke checks without publishing a release.
