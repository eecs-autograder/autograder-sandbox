#! /usr/bin/env python3

from setuptools import setup

setup(name='autograder-sandbox',
      version='1.0.0b0',
      description='Docker wrapper for securely running untrusted code',
      author='James Perretta',
      author_email='jameslp@umich.edu',
      packages=["autograder_sandbox"],
      install_requires=['redis>=2.10.5'])
