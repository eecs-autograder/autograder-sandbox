# Autograder Sandbox

This Python library uses Docker container functionality to create a secure, isolated environment for running untrusted code.
Full API documentation can be found at http://autograder-sandbox.readthedocs.io/en/latest/

## Requirements
- Python 3. For versions earlier than Python 3.5, you must install the [typing package](https://pypi.python.org/pypi/typing)
- Docker >= 1.10
- Redis >= 3.0

## Installation
1. Install [Docker](https://docs.docker.com/engine/installation/)
1. Install Redis (this is used to allow separate processes spawning containers to use distinct linux user IDs in their containers)
1. Install this library with pip: `pip install autograder-sandbox`

## Configuration
By default, the sandbox program tries to connect to Redis at localhost:6379. To change the host or port, set the AG_REDIS_HOST
and AG_REDIS_PORT environment variables, respectively.

## Basic usage
```
from autograder_sandbox import AutograderSandbox

with AutograderSandbox() as sandbox:
    result = sandbox.run_command(['echo', 'hello world'], timeout=10)
    print(result.stdout)
```
