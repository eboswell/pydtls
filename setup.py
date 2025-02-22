#!/usr/bin/env python
# PyDTLS setup script.

# Copyright 2017 Ray Brown
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# The License is also distributed with this work in the file named "LICENSE."
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""PyDTLS setup script

Install or create a distribution of the PyDTLS package.
"""

import sysconfig
from os import path, remove
from shutil import copy2, rmtree
from argparse import ArgumentParser
from pickle import dump, load
from setuptools import setup, Distribution
import datetime

NAME = "python3-dtls"
VERSION = "1.3.0+fb." + datetime.datetime.now().strftime("%Y%m%d%H%M")

if __name__ == "__main__":
    # Full upload sequence for new version:
    #    1. python setup.py bdist_wheel
    #    2. python setup.py bdist_wheel -p win32
    #    3. python setup.py bdist_wheel -p win_amd64
    #    4. twine upload dist/*

    parser = ArgumentParser(add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("command", nargs="*")
    parser.add_argument("-p", "--plat-name")
    args = parser.parse_known_args()[0]
    dist = "bdist_wheel" in args.command and not args.help
    plat_name = sysconfig.get_platform()
    plat_dist = dist and (args.plat_name or plat_name)
    if dist:
        try:
            from pypandoc import convert
            long_description = convert("README.md", "rst")\
                               .translate({ord("\r"): None})
            with open("README.rst", "wb") as readme:
                readme.write(long_description)
        except ModuleNotFoundError:
            # pandoc is not installed, fallback to using raw contents
            long_description = open('README.md').read()
    else:
        long_description = open("README.md").read()

    top_package_plat_files_file = "dtls_package_files"
    
    class BinaryDistribution(Distribution):
        """Distribution which always forces a binary package with platform name"""
        def has_ext_modules(foo):
            return True if plat_dist else False

    if dist:
        if plat_dist:
            top_package_plat_files = []
            package_files = True
            prebuilt_platform_root = "dtls/prebuilt"
            plat_name = args.plat_name if args.plat_name else plat_name
            if plat_name == "win32":
                platform = "win32-x86"
            elif plat_name in ["win_amd64", "win-amd64"]:
                platform = "win32-x86_64"
            else:
                package_files = False
            if package_files:
                prebuilt_path = prebuilt_platform_root + "/" + platform
                config = {"MANIFEST_DIR": prebuilt_path}
                exec(open(prebuilt_path + "/manifest.pycfg").read(), config)
                # top_package_plat_files = map(lambda x: prebuilt_path + "/" + x,
                #                              config["FILES"])
                top_package_plat_files = [prebuilt_path + "/" + x for x in config["FILES"]]
            # Save top_package_plat_files with the distribution archive
            with open(top_package_plat_files_file, "wb") as fl:
                dump(top_package_plat_files, fl)
        else:
            top_package_plat_files = []
    else:
        # Load top_package_files from the distribution archive, if present
        try:
            with open(top_package_plat_files_file, "rb") as fl:
                top_package_plat_files = load(fl)
        except IOError:
            top_package_plat_files = []
    top_package_extra_files = ["NOTICE",
                               "LICENSE",
                               "README.md",
                               "ChangeLog"] + top_package_plat_files
    if dist:
        for extra_file in top_package_extra_files:
            copy2(extra_file, "dtls")
    top_package_extra_files = [path.basename(f)
                               for f in top_package_extra_files]
    setup(name=NAME,
          version=VERSION,
          description="Python Datagram Transport Layer Security",
          author="Ray Brown",
          author_email="code@liquibits.com",
          maintainer="Bjoern Freise",
          maintainer_email="mcfreis@gmx.net",
          url="https://github.com/mcfreis/pydtls",
          license="Apache-2.0",
          classifiers=[
              'Development Status :: 5 - Production/Stable',
              'Intended Audience :: Developers',
              'Topic :: Security :: Cryptography',
              'Topic :: Software Development :: Libraries :: Python Modules',
              'License :: OSI Approved :: Apache Software License',
              'Operating System :: POSIX :: Linux',
              'Operating System :: Microsoft :: Windows',
              'Programming Language :: Python :: 3.6',
          ],
          long_description=long_description,
          packages=["dtls", "dtls.demux", "dtls.test"],
          package_data={"dtls": top_package_extra_files,
                        "dtls.test": ["makecerts",
                                      "makecerts_ec.bat",
                                      "openssl_ca.cnf",
                                      "openssl_server.cnf",
                                      "certs/*.pem"]},
          data_files=[('', [top_package_plat_files_file])] if plat_dist else [],
          distclass=BinaryDistribution, 
    )
    if dist:
        try:
            remove("README.rst")
        except FileNotFoundError:
            pass
        for extra_file in top_package_extra_files:
            remove("dtls/" + extra_file)
        if plat_dist:
            remove(top_package_plat_files_file)
        rmtree("%s.egg-info" % NAME, True)
        rmtree("build", True)
