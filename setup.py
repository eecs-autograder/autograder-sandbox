#! /usr/bin/env python3

from setuptools import setup

setup(name='autograder-sandbox',
      version='5.0.0rc1',
      description=('Python library for running untrusted '
                   'code in Docker containers'),
      author='James Perretta',
      author_email='jameslp@umich.edu',
      packages=["autograder_sandbox"],
      include_package_data=True,
      package_data={
          'autograder_sandbox': ['py.typed']
      },
      url='https://github.com/eecs280staff/autograder-sandbox',
      license='GNU Lesser General Public License v3',
      classifiers=['Programming Language :: Python :: 3.6'])
