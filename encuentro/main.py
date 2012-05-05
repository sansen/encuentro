# -*- coding: utf8 -*-

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

"""Main Encuentro code."""


import bz2
import json
import logging
import os
import pickle

from unicodedata import normalize

from encuentro import NiceImporter, platform

# gtk import and magic to work with twisted
with NiceImporter('gtk', 'python-gtk2', '2.16.0'):
    import gtk
with NiceImporter('twisted', 'python-twisted-bin', '8.2.0'):
    from twisted.internet import gtk2reactor
gtk2reactor.install()

from twisted.internet import reactor, defer
from twisted.web import client

from encuentro.network import Downloader, BadCredentialsError, CancelledError
from encuentro import wizard

EPISODES_URL = "http://www.taniquetil.com.ar/encuentro-v01.bz2"

BASEDIR = os.path.dirname(__file__)

logger = logging.getLogger('encuentro.main')

_normalize_cache = {}


def prepare_to_filter(text):
    """Prepare a text to filter.

    It receives unicode, but return simple lowercase ascii.
    """
    return ''.join(search_normalizer(c) for c in text)

def search_normalizer(char):
    """Normalize always to one char length."""
    try:
        return _normalize_cache[char]
    except KeyError:
        norm = normalize('NFKD', char).encode('ASCII', 'ignore').lower()
        if not norm:
            norm = '?'
        _normalize_cache[char] = norm
        return norm


class Status(object):
    """Status constants."""
    none, waiting, downloading, downloaded = \
                                'none waiting downloading downloaded'.split()


class EpisodeData(object):
    """Episode data."""
    _liststore_order = {
        'titulo': 0,
        'seccion': 1,
        'tematica': 2,
        'duracion': 3,
        'nroemis': 4,
        'state': 5,        # note that state and progress both point to row 5,
        'progress': 5,     # because any change in these will update the row
    }

    def __init__(self, titulo, seccion, sinopsis, tematica, duracion, nroemis,
                 state=None, progress=None, filename=None):
        self.titulo = titulo
        self.seccion = seccion
        self.sinopsis = sinopsis
        self.tematica = tematica
        self.duracion = duracion
        self.state = Status.none if state is None else state
        self.progress = progress
        self.filename = filename
        self.nroemis = nroemis
        self.to_filter = None
        self.set_filter()

    def set_filter(self):
        """Set the data to filter later."""
        self.to_filter = dict(
            titulo=prepare_to_filter(self.titulo),
            seccion=prepare_to_filter(self.seccion),
        )

    def __str__(self):
        return "<EpisodeData [%d] (%s) %r>" % (self.nroemis,
                                               self.state, self.titulo)

    def _filter(self, attrib_name, field_filter):
        """Check if filter is ok and highligh the attribute."""
        attrib_to_search = self.to_filter[attrib_name]
        t = attrib_real = getattr(self, attrib_name)
        pos1 = attrib_to_search.find(field_filter)
        if pos1 == -1:
            return False, attrib_real

        pos2 = pos1 + len(field_filter)
        result = ''.join(t[:pos1] + '<span background="yellow">' +
                         t[pos1:pos2] + '</span>' + t[pos2:])
        return True, result

    def get_row_data(self, field_filter):
        """Return the data for the liststore row."""
        if field_filter == '':
            title = self.titulo
            seccion = self.seccion
        else:
            # it's being filtered
            found_titulo, title = self._filter('titulo', field_filter)
            found_seccion, seccion = self._filter('seccion', field_filter)
            if not found_titulo and not found_seccion:
                # not matched any of both, don't show the row
                return

        data = (title, seccion, self.tematica, self.duracion, self.nroemis,
                self._get_nice_state(), self.sinopsis)
        return data

    def _get_nice_state(self):
        """A nicer state wording."""
        if self.state == Status.none:
            state = ''
        elif self.state == Status.waiting:
            state = 'Esperando'
        elif self.state == Status.downloading:
            state = 'Descargando: %s' % self.progress
        elif self.state == Status.downloaded:
            state = 'Terminado'
        else:
            raise ValueError("Bad state value: %r" % (self.state,))
        return state

    def update_row(self, row, **kwargs):
        """Update own attributes and value in the row."""
        for k, v in kwargs.items():
            setattr(self, k, v)
            try:
                pos = self._liststore_order[k]
            except KeyError:
                pass  # not a shown value
            else:
                if k == 'state' or k == 'progress':
                    v = self._get_nice_state()
                row[pos] = v


class PreferencesUI(object):
    """Preferences GUI."""

    def __init__(self, main, config_data):
        self.main = main
        self.config_data = config_data

        self.builder = gtk.Builder()
        self.builder.add_from_file(os.path.join(BASEDIR,
                                                'ui', 'preferences.glade'))
        self.builder.connect_signals(self)

        widgets = (
            'dialog', 'entry_user', 'entry_password', 'entry_downloaddir',
            'checkbutton_autorefresh',
        )

        for widget in widgets:
            obj = self.builder.get_object(widget)
            assert obj is not None, '%s must not be None' % widget
            setattr(self, widget, obj)

    def run(self, parent_pos=None):
        """Show the dialog."""
        self.entry_user.set_text(self.config_data.get('user', ''))
        self.entry_password.set_text(self.config_data.get('password', ''))
        self.entry_downloaddir.set_text(
                                    self.config_data.get('downloaddir', ''))
        self.checkbutton_autorefresh.set_active(
                                    self.config_data.get('autorefresh', False))

        if parent_pos is not None:
            x, y = parent_pos
            self.dialog.move(x + 50, y + 50)
        self.main.main_window.set_sensitive(False)
        self.dialog.run()

    def on_dialog_destroy(self, widget, data=None):
        """Save the data and hide the dialog."""
        usr = self.entry_user.get_text()
        password = self.entry_password.get_text()
        downloaddir = self.entry_downloaddir.get_text()
        autorefresh = self.checkbutton_autorefresh.get_active()
        new_cfg = dict(user=usr, password=password, downloaddir=downloaddir,
                       autorefresh=autorefresh)

        logger.info("Updating preferences config: %s", new_cfg)
        self.config_data.update(new_cfg)
        self.main.main_window.set_sensitive(True)
        self.dialog.hide()

    on_dialog_response = on_dialog_close = on_dialog_destroy
    on_button_clicked = on_dialog_destroy


class UpdateUI(object):
    """Update GUI."""

    def __init__(self, main):
        self.main = main
        self.closed = False

        self.builder = gtk.Builder()
        self.builder.add_from_file(os.path.join(BASEDIR,
                                                'ui', 'update.glade'))
        self.builder.connect_signals(self)

        widgets = (
            'dialog', 'textview', 'cancel_button',
        )

        for widget in widgets:
            obj = self.builder.get_object(widget)
            assert obj is not None, '%s must not be None' % widget
            setattr(self, widget, obj)

    def tview_insert(self, text):
        """Insert something in the textview's buffer."""
        _buffer = self.textview.get_buffer()
        _buffer.insert(_buffer.get_end_iter(), text)
        while gtk.events_pending():
            gtk.main_iteration()

    def run(self, parent_pos=None):
        """Show the dialog."""
        self.closed = False
        if parent_pos is not None:
            x, y = parent_pos
            self.dialog.move(x + 50, y + 50)

        self._update(self.tview_insert)
        self.main.main_window.set_sensitive(False)
        self.dialog.run()
        self.textview.get_buffer().set_text("")

    def on_dialog_destroy(self, widget, data=None):
        """Hide the dialog."""
        self.main.main_window.set_sensitive(True)
        self.closed = True
        self.dialog.hide()
    on_dialog_response = on_dialog_close = on_dialog_destroy

    @defer.inlineCallbacks
    def update(self, refresh_gui):
        """Trigger an update in background."""
        dummy = lambda text: None
        yield self._update(dummy)
        refresh_gui()

    @defer.inlineCallbacks
    def _update(self, tell_user):
        """Update the content from server."""
        self.closed = False

        logger.info("Updating episodes metadata")
        tell_user("Descargando la lista de episodios...\n")
        try:
            compressed = yield client.getPage(EPISODES_URL)
        except Exception, e:
            logger.error("Problem when downloading episodes: %s", e)
            tell_user("Hubo un PROBLEMA al bajar los episodios: " + str(e))
            return
        if self.closed:
            return

        tell_user("Descomprimiendo el archivo....\n")
        new_content = bz2.decompress(compressed)
        logger.debug("Downloaded data decompressed ok")

        tell_user("Actualizando los datos internos....\n")
        new_data = json.loads(new_content)
        logger.debug("Updating internal metadata (%d)", len(new_data))
        self.main.merge_episode_data(new_data)

        tell_user(u"¡Todo terminado bien!\n")
        self.on_dialog_destroy(None)


class SensitiveGrouper(object):
    """Centralize sensitiviness and tooltip management."""
    _tooltips = gtk.Tooltips()

    def __init__(self):
        self.items = {}

    def add(self, reference, toolb, menub, active_ttip, alternate_ttip):
        """Add an item.

        All items born with sensitiveness in False.
        """
        self.items[reference] = (toolb, menub, active_ttip, alternate_ttip)
        toolb.set_sensitive(False)
        menub.set_sensitive(False)

    def set_sensitive(self, reference, sensitiviness):
        """Set sensitiviness."""
        toolb, menub, active_ttip, alternate_ttip = self.items[reference]
        toolb.set_sensitive(sensitiviness)
        menub.set_sensitive(sensitiviness)

        # set a different tooltip to the toolbar button
        tip_text = (alternate_ttip, active_ttip)[int(sensitiviness)]
        toolb.set_tooltip(self._tooltips, tip_text)


class MainUI(object):
    """Main GUI class."""

    _data_file = os.path.join(platform.data_dir, 'encuentro.data')
    _config_file = os.path.join(platform.config_dir, 'encuentro.conf')
    print "Using data file:", repr(_data_file)
    print "Using configuration file:", repr(_config_file)

    def __init__(self, version):
        self.version = version
        self.main_window_active = None  # means active, see docstring below
        self.builder = gtk.Builder()
        self.builder.add_from_file(os.path.join(BASEDIR,
                                                'ui', 'main.glade'))
        self.builder.connect_signals(self)

        widgets = (
            'main_window', 'programs_store', 'programs_treeview', 'toolbar',
            'toolbutton_play', 'toolbutton_download', 'toolbutton_needconfig',
            'dialog_quit', 'dialog_quit_label', 'dialog_alert', 'dialog_error',
            'rb_menu', 'rbmenu_play', 'rbmenu_cancel', 'rbmenu_download',
            'menu_download', 'menu_play', 'aboutdialog', 'statusicon',
        )

        for widget in widgets:
            obj = self.builder.get_object(widget)
            assert obj is not None, '%s must not be None' % widget
            setattr(self, widget, obj)

        # stupid glade! it does not let me put the cell renderer
        # expanded *in the column*
        columns = self.programs_treeview.get_columns()
        for col_number in (3, 4):
            column = columns[col_number]
            cell_renderer = column.get_cell_renderers()[0]
            column.clear()
            column.pack_end(cell_renderer, expand=True)
            column.add_attribute(cell_renderer, "text", col_number)

        # get data from file, or empty
        if os.path.exists(self._data_file):
            with open(self._data_file) as fh:
                self.programs_data = pickle.load(fh)
        else:
            self.programs_data = {}
        logger.info("Episodes metadata loaded (%d)", len(self.programs_data))

        # check if we need to update "to_filter"
        one_program = self.programs_data.values()[:1]
        if one_program:
            old_to_filter = getattr(one_program[0], 'to_filter', None)
            if old_to_filter is None or isinstance(old_to_filter, basestring):
                for p in self.programs_data.itervalues():
                    p.set_filter()

        # get config from file, or defaults
        if os.path.exists(self._config_file):
            with open(self._config_file) as fh:
                self.config = pickle.load(fh)
        else:
            self.config = {}

        # log the config, but without user and pass
        safecfg = self.config.copy()
        if 'user' in safecfg:
            safecfg['user'] = '<hidden>'
        if 'password' in safecfg:
            safecfg['password'] = '<hidden>'
        logger.debug("Configuration loaded: %s", safecfg)

        # we have a default for download dir
        if not self.config.get('downloaddir'):
            self.config['downloaddir'] = platform.get_download_dir()

        self.update_dialog = UpdateUI(self)
        self.preferences_dialog = PreferencesUI(self, self.config)

        self.downloader = Downloader(self.config)
        self.episodes_to_download = []
        self._downloading = False

        # widget sensitiviness
        self.sensit_grouper = sg = SensitiveGrouper()
        sg.add('play', self.toolbutton_play, self.menu_play, u"Reproducir",
               u"Reproducir - El episodio debe estar descargado para "
               u"poder verlo.")
        sg.add('download', self.toolbutton_download, self.menu_download,
               u"Descargar", u"Descargar - No se puede descargar si ya está "
               u"descargado o falta alguna configuración en el programa.")

        # icons
        icons = []
        for size in (16, 32, 48, 64, 128):
            iconfile = os.path.join(BASEDIR, 'logos', 'icon-%d.png' % (size,))
            icons.append(gtk.gdk.pixbuf_new_from_file(iconfile))
        self.main_window.set_icon_list(*icons)
        self.statusicon.set_from_pixbuf(icons[0])

        self._non_glade_setup()
        self.refresh_treeview()
        self.main_window.show()
        self._restore_layout()

        # update stuff if needed to
        if 'autorefresh' in self.config and self.config['autorefresh']:
            self.update_dialog.update(self._restore_layout)

        logger.debug("Main UI started ok")

        if not self.config.get('nowizard'):
            wizard.start(self, self._have_config, self._have_metadata)
        self.review_need_something_indicator()

    def _have_config(self):
        """Return if some config is needed."""
        return self.config.get('user') and self.config.get('password')

    def _have_metadata(self):
        """Return if metadata is needed."""
        return bool(self.programs_data)

    def review_need_something_indicator(self):
        """Start the wizard if needed, or hide the need config button."""
        if not self._have_config() or not self._have_metadata():
            # config needed, put the alert if not there
            if not self.toolbutton_needconfig.get_property("visible"):
                self.toolbutton_needconfig.show()
            # also turn off the download button
            self.sensit_grouper.set_sensitive('download', False)
        else:
            # no config needed, remove the alert if there
            if self.toolbutton_needconfig.get_property("visible"):
                self.toolbutton_needconfig.hide()
            # also turn on the download button
            self.sensit_grouper.set_sensitive('download', True)

    def on_toolbutton_needconfig_clicked(self, widget, data=None):
        """The 'need config' toolbar button was clicked, open the wizard."""
        wizard.start(self, self._have_config, self._have_metadata)

    def _restore_layout(self):
        """Get info from config and change layouts."""
        if 'mainwin_size' in self.config:
            self.main_window.resize(*self.config['mainwin_size'])

        if 'mainwin_position' in self.config:
            self.main_window.move(*self.config['mainwin_position'])

        treeview_columns = self.programs_treeview.get_columns()
        if 'cols_width' in self.config:
            for col, size in zip(treeview_columns, self.config['cols_width']):
                col.set_fixed_width(size)
        else:
            width = self.main_window.get_size()[0] // len(treeview_columns)
            for col in treeview_columns:
                col.set_fixed_width(width)

        if 'cols_order' in self.config:
            self.programs_store.set_sort_column_id(*self.config['cols_order'])

        if 'selected_row' in self.config:
            path = self.config['selected_row']
            self.programs_treeview.scroll_to_cell(path, use_align=True,
                                                  row_align=.5)
            self.programs_treeview.set_cursor(path)
            self.programs_treeview.grab_focus()

    def _non_glade_setup(self):
        """Stuff I don't know how to do it in Glade."""
        tree_selection = self.programs_treeview.get_selection()

        # enable treeview multiple selection
        tree_selection.set_mode(gtk.SELECTION_MULTIPLE)

        # connect the selection 'changed' signal; note that this is different
        # to get the 'treeview cursor changed' signal from Glade, as the result
        # for get_selected_rows() is not the same
        tree_selection.connect('changed',
                               self.on_programs_treeview_selection_changed)

    def merge_episode_data(self, new_data):
        """Merge new data to current programs data."""
        for d in new_data:
            # v01 of json file
            nroemis = d['nroemis']
            sinopsis = d['sinopsis']
            tematica = d['tematica']
            seccion = d['seccion']
            titulo = d['titulo']
            duracion = d['duracion']

            try:
                epis = self.programs_data[d['nroemis']]
            except KeyError:
                ed = EpisodeData(titulo=titulo, seccion=seccion,
                                 sinopsis=sinopsis, tematica=tematica,
                                 duracion=duracion, nroemis=nroemis)
                self.programs_data[nroemis] = ed
            else:
                epis.titulo = titulo
                epis.sinopsis = sinopsis
                epis.tematica = tematica
                epis.seccion = seccion
                epis.duracion = duracion
                epis.set_filter()

        # refresh the treeview and save the data
        self.refresh_treeview()
        self._save_states()

    def refresh_treeview(self, field_filter=''):
        """Update the liststore of the programs."""
        columns = [self.programs_store.get_column_type(i)
                   for i in range(self.programs_store.get_n_columns())]
        prv_order_col, prv_order_dir = self.programs_store.get_sort_column_id()

        new_liststore = gtk.ListStore(*columns)
        for p in self.programs_data.itervalues():
            data = p.get_row_data(field_filter)
            if data is not None:
                new_liststore.append(data)

        if prv_order_col is not None:
            new_liststore.set_sort_column_id(prv_order_col, prv_order_dir)
        self.programs_treeview.set_model(new_liststore)

        # pograms_store was defined before, yes! pylint: disable=W0201
        self.programs_store = new_liststore

    def on_filter_entry_changed(self, widget, data=None):
        """Filter the rows for something."""
        text = widget.get_text().decode('utf8')
        text = prepare_to_filter(text)
        self.refresh_treeview(text)

    def _close(self):
        """Still time to decide if want to close or not."""
        logger.info("Attempt to close the program")
        for idx, program in self.programs_data.iteritems():
            state = program.state
            if state == Status.waiting or state == Status.downloading:
                logger.debug("Active (%s) download: %s", state, program)
                break
        else:
            # all fine, save all and quit
            logger.info("Saving states and quitting")
            self._save_states()
            return False

        # stuff pending
        # we *sure* have idx and program; pylint: disable=W0631
        logger.info("Active downloads! %s (%r)", idx, program.titulo)
        m = (u"Al menos un programa está todavía en proceso de descarga!\n\n"
             u"Episodio %s: %s\n" % (idx, program.titulo))
        self.dialog_quit_label.set_text(m)
        opt_quit = self.dialog_quit.run()
        self.dialog_quit.hide()
        if not opt_quit:
            logger.info("Quit cancelled")
            return True

        # quit anyway, put all downloading and pending episodes to none
        logger.info("Fixing episodes, saving state and exiting")
        for program in self.programs_data.itervalues():
            state = program.state
            if state == Status.waiting or state == Status.downloading:
                program.state = Status.none
        self._save_states()
        return False

    def on_main_window_delete_event(self, widget, event):
        """Windows was deleted."""
        return self._close()

    def on_menu_quit_activate(self, widget):
        """Quit from the menu."""
        # strange semantics because we use the same True/False that does the
        # trick for event propagation
        abort_close = self._close()
        if not abort_close:
            self.on_main_window_destroy(None)

    def _save_states(self):
        """Dump all states and info to disk."""
        with open(self._data_file, 'w') as fh:
            pickle.dump(self.programs_data, fh)

        self.config['mainwin_size'] = self.main_window.get_size()
        self.config['mainwin_position'] = self.main_window.get_position()
        treeview_columns = self.programs_treeview.get_columns()
        self.config['cols_width'] = [c.get_width() for c in treeview_columns]

        cols_order = self.programs_store.get_sort_column_id()
        if cols_order != (None, None):
            self.config['cols_order'] = cols_order

        tree_selection = self.programs_treeview.get_selection()
        _, pathlist = tree_selection.get_selected_rows()
        if len(pathlist) > 0:
            self.config['selected_row'] = pathlist[0]

        with open(self._config_file, 'w') as fh:
            pickle.dump(self.config, fh)

    def on_main_window_destroy(self, widget, data=None):
        """Stop all other elements than the GUI itself."""
        self.downloader.shutdown()
        reactor.stop()

    def on_toolbutton_preferencias_clicked(self, widget, data=None):
        """Open the preference dialog."""
        self.preferences_dialog.run(self.main_window.get_position())
        self.review_need_something_indicator()
    on_menu_preferences_activate = on_toolbutton_preferencias_clicked

    def on_toolbutton_update_clicked(self, widget, data=None):
        """Open the preference dialog."""
        self.update_dialog.run(self.main_window.get_position())
        self.review_need_something_indicator()
    on_menu_update_activate = on_toolbutton_update_clicked

    def on_toolbutton_download_clicked(self, widget, data=None):
        """Download the episode(s)."""
        tree_selection = self.programs_treeview.get_selection()
        _, pathlist = tree_selection.get_selected_rows()
        for path in pathlist:
            row = self.programs_store[path]
            self._queue_download(row)
    on_menu_download_activate = on_toolbutton_download_clicked

    @defer.inlineCallbacks
    def _queue_download(self, row):
        """User indicated to download something."""
        episode = self.programs_data[row[4]]  # 4 is the episode number
        logger.debug("Download requested of %s", episode)
        if episode.state != Status.none:
            logger.debug("Download denied, episode %s is not in downloadeable "
                         "state.", episode.nroemis)
            return
        episode.update_row(row, state=Status.downloading, progress="encolado")

        self.episodes_to_download.append(row)
        if self._downloading:
            return

        logger.debug("Downloads: starting")
        self._downloading = True
        while self.episodes_to_download:
            row = self.episodes_to_download.pop(0)
            try:
                filename, episode = yield self._episode_download(row)
            except CancelledError:
                logger.debug("Got a CancelledError!")
                episode.update_row(row, state=Status.none)
            except BadCredentialsError:
                logger.debug("Bad credentials error!")
                self._show_message(self.dialog_alert)
                episode.update_row(row, state=Status.none)
            except Exception, e:
                logger.debug("Unknown download error: %s", e)
                self._show_message(self.dialog_error, str(e))
                episode.update_row(row, state=Status.none)
            else:
                logger.debug("Episode downloaded: %s", episode)
                episode.update_row(row, state=Status.downloaded,
                                   filename=filename)
            self._check_download_play_buttons()
        self._downloading = False
        logger.debug("Downloads: finished")

    def _show_message(self, dialog, text=None):
        """Show different download errors."""
        logger.debug("Showing a message: %r (%s)", text, dialog)

        # error text can be produced by windows, try to to sanitize it
        if isinstance(text, str):
            try:
                text = text.decode("utf8")
            except UnicodeDecodeError:
                try:
                    text = text.decode("latin1")
                except UnicodeDecodeError:
                    text = repr(text)

        if text is not None:
            hbox = dialog.get_children()[0].get_children()[0]
            label = hbox.get_children()[1].get_children()[0]
            label.set_text(text)
        configure = dialog.run()
        dialog.hide()
        if configure == 1:
            self.preferences_dialog.run(self.main_window.get_position())

    @defer.inlineCallbacks
    def _episode_download(self, row):
        """Effectively download an episode."""
        episode_number = row[4]  # 4 is the episode number
        episode = self.programs_data[episode_number]
        logger.debug("Effectively downloading episode %d", episode_number)
        episode.update_row(row, state=Status.downloading,
                           progress="comenzando...")

        def update_progress_cb(progress):
            """Update the progress and refreshes the treeview."""
            episode.update_row(row, progress=progress)

        # download!
        fname = yield self.downloader.download(episode_number,
                                               update_progress_cb)
        defer.returnValue((fname, episode))

    def on_toolbutton_play_clicked(self, widget, data=None):
        """Play the episode."""
        tree_selection = self.programs_treeview.get_selection()
        _, pathlist = tree_selection.get_selected_rows()
        if len(pathlist) != 1:
            print "ERROR: play_clicked must receive only one selection"
            return

        row = self.programs_store[pathlist[0]]
        self._play_episode(row)
    on_menu_play_activate = on_toolbutton_play_clicked

    def _play_episode(self, row):
        """Play an episode."""
        episode_number = row[4]  # 4 is the episode number
        episode = self.programs_data[episode_number]
        downloaddir = self.config.get('downloaddir', '')
        filename = os.path.join(downloaddir, episode.filename)

        logger.info("Play requested of %s", episode)
        if os.path.exists(filename):
            # pass file:// url with absolute path
            fullpath = 'file://' + os.path.abspath(filename)
            logger.info("Playing %r", fullpath)
            platform.open_file(fullpath)
        else:
            logger.warning("Aborted playing, file not found: %r", filename)
            msg = u"No se encontró el archivo para reproducir: " + repr(
                                                                    filename)
            self._show_message(self.dialog_error, msg)
            episode.update_row(row, state=Status.none)

    def on_any_treeviewcolumn_clicked(self, widget, data=None):
        """Clicked on the column title.

        Note that the received widget is the column itself.
        """
        # get previous order and calculate new one for current column
        prev_order = getattr(widget, '_order', None)
        if prev_order is None or prev_order == gtk.SORT_DESCENDING:
            new_order = gtk.SORT_ASCENDING
        else:
            new_order = gtk.SORT_DESCENDING

        # store the order and handle indicator
        widget._order = new_order
        widget.set_sort_indicator(True)
        widget.set_sort_order(new_order)

    def on_programs_treeview_row_activated(self, treeview, path, view_column):
        """Double click on the episode, download or play."""
        row = self.programs_store[path]
        episode = self.programs_data[row[4]]  # 4 is the episode number
        logger.debug("Double click in %s", episode)
        if episode.state == Status.downloaded:
            self._play_episode(row)
        elif episode.state == Status.none:
            if self._have_config():
                self._queue_download(row)
            else:
                logger.debug("Not starting download because no config.")
                t = (u"No se puede arrancar una descarga porque la "
                     u"configuración está incompleta.")
                self._show_message(self.dialog_alert, t)

    def on_programs_treeview_button_press_event(self, widget, event):
        """Support for right-button click."""
        if event.button != 3:  # right click
            return
        cursor = widget.get_path_at_pos(int(event.x), int(event.y))
        path = cursor[0][0]
        row = self.programs_store[path]
        episode = self.programs_data[row[4]]  # 4 is the episode number
        state = episode.state
        if state == Status.downloaded:
            self.rbmenu_play.set_sensitive(True)
            self.rbmenu_cancel.set_sensitive(False)
            self.rbmenu_download.set_sensitive(False)
        elif state == Status.downloading or state == Status.waiting:
            self.rbmenu_play.set_sensitive(False)
            self.rbmenu_cancel.set_sensitive(True)
            self.rbmenu_download.set_sensitive(False)
        elif state == Status.none:
            self.rbmenu_play.set_sensitive(False)
            self.rbmenu_cancel.set_sensitive(False)
            self.rbmenu_download.set_sensitive(True)
        self.rb_menu.popup(None, None, None,
                           event.button, event.time, data=row)

    def on_rbmenu_play_activate(self, widget):
        """Play an episode."""
        path = self.programs_treeview.get_cursor()[0]
        row = self.programs_store[path]
        self._play_episode(row)

    def on_rbmenu_cancel_activate(self, widget):
        """Cancel current download."""
        logger.info("Cancelling download.")
        path = self.programs_treeview.get_cursor()[0]
        row = self.programs_store[path]
        episode = self.programs_data[row[4]]  # 4 is the episode number
        episode.update_row(row, state=Status.downloading,
                           progress="cancelando...")
        self.downloader.cancel()

    def on_rbmenu_download_activate(self, widget):
        """Download an episode."""
        path = self.programs_treeview.get_cursor()[0]
        row = self.programs_store[path]
        self._queue_download(row)

    def on_programs_treeview_selection_changed(self, tree_selection):
        """Get all selected rows and adjust buttons accordingly."""
        self._check_download_play_buttons(tree_selection)

    def _check_download_play_buttons(self, tree_selection=None):
        """Set both buttons state according to the selected episodes."""
        if tree_selection is None:
            tree_selection = self.programs_treeview.get_selection()
            if tree_selection is None:
                return
        _, pathlist = tree_selection.get_selected_rows()

        # 'play' button should be enabled if only one row is selected and
        # its state is 'downloaded'
        play_enabled = False
        if len(pathlist) == 1:
            row = self.programs_store[pathlist[0]]
            episode = self.programs_data[row[4]]  # 4 is the episode number
            if episode.state == Status.downloaded:
                play_enabled = True
        self.sensit_grouper.set_sensitive('play', play_enabled)

        # 'download' button should be enabled if at least one of the selected
        # rows is in 'none' state, and if config is ok
        download_enabled = False
        if self._have_config():
            for path in pathlist:
                row = self.programs_store[path]
                episode = self.programs_data[row[4]]  # 4 is the episode number
                if episode.state == Status.none:
                    download_enabled = True
                    break
        self.sensit_grouper.set_sensitive('download', download_enabled)

    def on_menu_about_activate(self, widget):
        """Show the 'About of' dialog."""
        self.aboutdialog.set_property('version', str(self.version))
        self.aboutdialog.run()
        self.aboutdialog.hide()

    def on_statusicon_activate(self, *a):
        """Switch visibility for the main window.

        The 'main_window_active' is None if window should be active, or the
        last position when hidden (so it's properly restored then).
        """
        if self.main_window_active is None:
            # was active, let's hide
            self.main_window_active = self.main_window.get_position()
            self.main_window.hide()
        else:
            # we have the stored position!
            position = self.main_window_active
            self.main_window_active = None
            self.main_window.show()
            self.main_window.move(*position)


if __name__ == '__main__':
    MainUI()
    reactor.run()
