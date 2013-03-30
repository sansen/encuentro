# -*- coding: UTF-8 -*-

# Copyright 2013 Facundo Batista
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

"""The system configuration."""

import os
import pickle


class _Config(dict):
    """The configuration."""

    SYSTEM = 'system'

    def __init__(self):
        self._fname = None

    def init(self, fname):
        """Initialize and load config."""
        self._fname = fname
        if not os.path.exists(fname):
            # default to an almost empty dict
            self[self.SYSTEM] = {}
            return

        with open(fname, 'rb') as fh:
            saved_dict = pickle.load(fh)
        self.update(saved_dict)

        # for compatibility, put the system container if not there
        if self.SYSTEM not in self:
            self[self.SYSTEM] = {}

    def save(self):
        """Save the config to disk."""
        # we don't want to pickle this class, but the dict itself
        raw_dict = self.copy()
        with open(self._fname, 'wb') as fh:
            pickle.dump(raw_dict, fh)


config = _Config()
