# Autograder Sandbox

This Python library uses Docker container functionality to create a secure, isolated environment for running untrusted code.

## Requirements
- Python >= 3.4
- Docker >= 1.10
- Redis >= 3.0

## Installation
1. Install [Docker](https://docs.docker.com/engine/installation/)
1. Install Redis (this is used to allow separate processes spawning containers to use distinct linux user IDs in their containers)
1. Run `python3 setup.py install`

To run the tests, run `python3 -m autograder_sandbox.tests`

## Configuration
By default, the sandbox program tries to connect to Redis at localhost:6379. To change the host or port, set the AG_REDIS_HOST
and AG_REDIS_PORT environment variables, respectively.
