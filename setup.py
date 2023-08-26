#! /usr/bin/env python3

from setuptools import setup, find_packages

setup(name='autograder-sandbox',
      version='6.0.0a4',
      description=('Python library for running untrusted '
                   'code in Docker containers'),
      author='James Perretta',
      author_email='jameslp@umich.edu',
      packages=find_packages(),
      include_package_data=True,
      zip_safe=False,
      url='https://github.com/eecs280staff/autograder-sandbox',
      license='GNU Lesser General Public License v3',
      classifiers=['Programming Language :: Python :: 3.6']
)
