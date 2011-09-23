#!/usr/bin/env python

# Copyright 2011 Facundo Batista
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3, as published
# by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranties of
# MERCHANTABILITY, SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR
# PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# For further info, check  https://launchpad.net/encuentro

"""Build tar.gz for encuentro.

Needed packages to run (using Debian/Ubuntu package names):

    python-zope.testbrowser 3.5.1
    python-mechanize 0.1.11
    python-twisted-bin 8.2.0
    python-gtk2 2.16.0
    python-xdg 0.15
"""

import os

from distutils.command.install import install
from distutils.core import setup


class CustomInstall(install):
    """Custom installation class on package files.

    It copies all the files into the "PREFIX/share/PROJECTNAME" dir.
    """
    def run(self):
        """Run parent install, and then save the install dir in the script."""
        install.run(self)

        # fix installation path in the script(s)
        for script in self.distribution.scripts:
            script_path = os.path.join(self.install_scripts,
                                       os.path.basename(script))
            with open(script_path, 'rb') as fh:
                content = fh.read()
            content = content.replace('@ INSTALLED_BASE_DIR @',
                                      self._custom_data_dir)
            with open(script_path, 'wb') as fh:
                fh.write(content)

        # fix the icon path, and save the .desktop file where it should be
        src_desktop = self.distribution.get_name() + '.desktop'
        if not os.path.exists(self._custom_apps_dir):
            os.makedirs(self._custom_apps_dir)
        dst_desktop = os.path.join(self._custom_apps_dir, src_desktop)

        with open(src_desktop, 'rb') as fh:
            content = fh.read()
        icon = os.path.join(self._custom_data_dir,
                            'encuentro', 'logos', 'icon-32.png')
        content = content.replace('@ INSTALLED_ICON @', icon)
        with open(dst_desktop, 'wb') as fh:
            fh.write(content)

    def finalize_options(self):
        """Alter the installation path."""
        install.finalize_options(self)

        # the data path is under 'prefix'
        data_dir = os.path.join(self.prefix, "share",
                                self.distribution.get_name())
        apps_dir = os.path.join(self.prefix, "share", "applications")

        # if we have 'root', put the building path also under it (used normally
        # by pbuilder)
        if self.root is None:
            build_dir = data_dir
        else:
            build_dir = os.path.join(self.root, data_dir[1:])
            apps_dir = os.path.join(self.root, apps_dir[1:])

        # change the lib install directory so all package files go inside here
        self.install_lib = build_dir

        # save this custom data dir to later change the scripts
        self._custom_data_dir = data_dir
        self._custom_apps_dir = apps_dir


setup(
    name='encuentro',
    version='0.2',
    license='GPL-3',
    author='Facundo Batista',
    author_email='facundo@taniquetil.com.ar',
    description='Search, download and see the wonderful Encuentro content.',
    long_description='Simple application that allows to search, download ' \
                      'and see the content of the Encuentro channel.',
    url='https://launchpad.net/encuentro',

    packages=["encuentro"],
    package_data={"encuentro": ["ui/*.glade", "logos/icon-32.png"]},
    scripts=["bin/encuentro"],

    cmdclass={
        'install': CustomInstall,
    },
)
