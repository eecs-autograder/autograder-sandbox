#! /bin/bash

set -e

pip install pip-tools
pip-sync requirements.txt requirements-dev.txt
pip install --editable .
