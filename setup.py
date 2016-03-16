#!/usr/bin/env python

from setuptools import setup

setup(name='tomato',
    version='0.1',
    author='Sertan Senturk',
    author_email='contact AT sertansenturk DOT com',
    license='agpl 3.0',
    description='Turkish-Ottoman Makam Music Analysis Toolbox',
    url='http://sertansenturk.com',
    packages=['tomato'],
    install_requires=[
        "numpy",
    ],
)

