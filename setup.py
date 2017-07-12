#! /usr/bin/env python3

from setuptools import setup  # type: ignore
import autograder_sandbox

setup(name='autograder-sandbox',
      version=autograder_sandbox.VERSION,
      description=('Python library for running untrusted '
                   'code in Docker containers'),
      author='James Perretta',
      author_email='jameslp@umich.edu',
      packages=["autograder_sandbox"],
      url='https://github.com/eecs280staff/autograder-sandbox',
      license='GNU Lesser General Public License v3',
      install_requires=['redis>=2.10.5'],
      classifiers=['Programming Language :: Python :: 3.5'])
