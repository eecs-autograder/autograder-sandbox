# Autograder Sandbox

This Python library uses Docker container functionality to create a secure, isolated environment for running untrusted code.
Full API documentation can be found at http://autograder-sandbox.readthedocs.io/en/latest/

## Requirements
- Python >= 3.5
- Docker >= 1.10
- Redis >= 3.0

## Installation
1. Install [Docker](https://docs.docker.com/engine/installation/)
1. Install Redis (this is used to allow separate processes spawning containers to use distinct linux user IDs in their containers, which is important when using resource limits)
1. Install this library with pip: `pip install autograder-sandbox`
The first time you start a sandbox (using a context manager), the appropriate Docker image will be downloaded automatically.

## Configuration
### Redis
By default, the sandbox program tries to connect to Redis at localhost:6379. To change the host or port, set the AG_REDIS_HOST
and AG_REDIS_PORT environment variables, respectively.

### Docker Image
The Docker image used by default is [jameslp/autograder-sandbox](https://hub.docker.com/r/jameslp/autograder-sandbox/).
If using a custom image, begin your custom Dockerfile with `FROM jameslp/autograder-sandbox:latest`. Then, when creating the sandbox instance, pass the name of your custom image to the `docker_image` parameter. Alternatively, you can set the SANDBOX_DOCKER_IMAGE environment variable to that name.

## Basic usage
```
from autograder_sandbox import AutograderSandbox

with AutograderSandbox() as sandbox:
    result = sandbox.run_command(['echo', 'hello world'], timeout=10)
    print(result.stdout)
```

### Changelog
Versioning scheme:
- 0.0.x releases contain minor tweaks or bug fixes.
- 0.x.0 releases contain new features.
- x.0.0 releases may contain backwards-incompatible changes.

2.0.1 - Hotfix for output decoding issue.
- Previously, stdout and stderr were not being decoded on TimeoutExpired or CalledProcessError. This release fixes this.

2.0.0 - Removes support for versions of Python < 3.5
- Issues fixed:
    - [#4](/james-perretta/autograder-sandbox/issues/4)
    - [#5](/james-perretta/autograder-sandbox/issues/5)
    - [#6](/james-perretta/autograder-sandbox/issues/6)
- Changes to AutograderSandbox constructor parameters:
    - Added `docker_image` and `container_create_timeout`
- Changes to AutograderSandbox.run_command() parameters:
    - Added `encoding` and `errors`
    - Renamed `input_content` to `input`
    - Renamed `raise_on_failure` to `check`
- AutograderSandbox.run_command() now returns subprocess.CompletedProcess. The `stdout` and `stderr` fields of the returned objects will always be strings.
- AutograderSandbox.run_command() now raises subprocess.TimeoutExpired if the time limit is exceeded. There is no longer a `timed_out` field of the returned object.

1.0.0 - Initial release

