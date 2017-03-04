#! /usr/bin/env python3

from setuptools import setup  # type: ignore

setup(name='autograder-sandbox',
      version='2.0.0',
      description=('Python library for running untrusted '
                   'code in Docker containers'),
      author='James Perretta',
      author_email='jameslp@umich.edu',
      packages=["autograder_sandbox"],
      url='https://github.com/eecs280staff/autograder-sandbox',
      license='GNU Lesser General Public License v3',
      install_requires=['redis>=2.10.5'])
