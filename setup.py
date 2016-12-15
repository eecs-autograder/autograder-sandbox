#! /usr/bin/env python3

import sys
import subprocess

from setuptools import setup

try:
    subprocess.check_call(['docker', 'pull', 'jameslp/autograder-sandbox'])
except subprocess.CalledProcessError as e:
    print(e)
    print('Error pulling Docker image. Are you sure Docker is running?')
    sys.exit(1)

setup(name='Autograder Sandbox',
      version='1.0',
      description='Docker wrapper for securely running untrusted code',
      author='James Perretta',
      author_email='jameslp@umich.edu',
      packages=['autograder_sandbox'],
      install_requires=['redis>=2.10.5'])
