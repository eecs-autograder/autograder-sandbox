#! /usr/bin/env python3

from setuptools import setup  # type: ignore

setup(name='autograder-sandbox',
      version='4.0.1',
      description=('Python library for running untrusted '
                   'code in Docker containers'),
      author='James Perretta',
      author_email='jameslp@umich.edu',
      packages=["autograder_sandbox"],
      include_package_data=True,
      url='https://github.com/eecs280staff/autograder-sandbox',
      license='GNU Lesser General Public License v3',
      install_requires=['redis>=2.10.5'],
      classifiers=['Programming Language :: Python :: 3.5'])
