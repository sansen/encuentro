# Copyright 2011-2020 Facundo Batista
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

"""The package."""

import sys

IMPORT_MSG = """
ERROR! Problema al importar %(module)r

Probablemente falte instalar una dependencia.  Se necesita tener instalado
el paquete %(package)r versión %(version)s o superior.
"""


class NiceImporter:
    """Show nicely successful and errored imports."""
    def __init__(self, module, package, version):
        self.module = module
        self.package = package
        self.version = version

    def __enter__(self):
        pass

    def _get_version(self):
        """Get the version of a module."""
        mod = sys.modules[self.module]
        for attr in ('version', '__version__', 'ver', 'PYQT_VERSION_STR'):
            v = getattr(mod, attr, None)
            if v is not None:
                return v
        return "<desconocida>"

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            version = self._get_version()
            print("Módulo %r importado ok, versión %r" % (self.module, version))
        else:
            print(IMPORT_MSG % dict(module=self.module, package=self.package,
                                    version=self.version))

        # consume the exception!
        return True


# test the packages
with NiceImporter('xdg', 'python-xdg', '0.15'):
    import xdg  # NOQA
with NiceImporter('requests', 'python-requests', '2.2.1'):
    import requests  # NOQA
with NiceImporter('PyQt5.QtCore', 'PyQt5', '5.7'):
    import PyQt5.QtCore  # NOQA
with NiceImporter('defer', 'python-defer', '1.0.6'):
    import defer  # NOQA
