#!/usr/bin/env python3

import os
import sys
import subprocess

from setuptools import setup

try:
    subprocess.check_call(
        ['docker', 'build', '-t', 'autograder',
         os.path.join('autograder_sandbox', 'docker-image-setup')])
except subprocess.CalledProcessError as e:
    print(e)
    print('Error building Docker image. Are you sure Docker is running?')
    sys.exit(1)

setup(name='Autograder Sandbox',
      version='1.0',
      description='Docker wrapper for securely running untrusted code',
      author='James Perretta',
      author_email='jameslp@umich.edu',
      packages=['autograder_sandbox'],
      install_requires=['redis>=2.10.5'])
