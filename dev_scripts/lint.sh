#! /bin/bash

set -xe

script_dir=$(dirname "$(realpath $0)")

isort --check autograder_sandbox
# black --check autograder_sandbox
pycodestyle \
    --ignore=W503,E133,E704,E501 \
    autograder_sandbox
pydocstyle autograder_sandbox
pyright
