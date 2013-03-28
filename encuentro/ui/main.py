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

"""The main window."""

import logging
import os
import pickle

try:
    import pynotify
except ImportError:
    pynotify = None

from PyQt4.QtGui import (
    QAction,
    QCheckBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStyle,
    qApp,
)
from twisted.internet import defer

from encuentro import platform, data, update
from encuentro.data import Status
from encuentro.network import (
    BadCredentialsError,
    CancelledError,
    all_downloaders,
)
from encuentro.ui import central_panel, wizard, preferences

logger = logging.getLogger('encuentro.main')

# tooltips for buttons enabled and disabled
TTIP_PLAY_E = u'Reproducir el programa'
TTIP_PLAY_D = (
    u"Reproducir - El episodio debe estar descargado para poder verlo."
)
TTIP_DOWNLOAD_E = u'Descargar el programa de la web'
TTIP_DOWNLOAD_D = (
    u"Descargar - No se puede descargar si ya está descargado o falta "
    u"alguna configuración en el programa."
)

# FIXME: need an About dialog, connected to the proper signals below
#   title: Encuentro <version>   <-- need to receive the version when exec'ed
#   comments: Simple programa que permite buscar, descargar y ver
#             contenido del canal Encuentro y otros.
#   smaller: Copyright 2010-2013 Facundo  Batista
#   url: http://encuentro.taniquetil.com.ar
#   somewhere (maybe with a button), the license: the content of LICENSE.txt

# FIXME: need to put an icon that looks nice in alt-tab, taskbar, unity, etc

# FIXME: need to make Encuentro "iconizable"

# FIXME: set up a status icon, when the icon is clicked the main window should
# appear or disappear, keeping the position and size of the position after
# the sequence


class MainUI(QMainWindow):
    """Main UI."""

    _config_file = os.path.join(platform.config_dir, 'encuentro.conf')
    print "Using configuration file:", repr(_config_file)
    _programs_file = os.path.join(platform.data_dir, 'encuentro.data')

    def __init__(self, version, reactor_stop):
        super(MainUI, self).__init__()
        self.reactor_stop = reactor_stop
        self.finished = False
        # FIXME: size and positions should remain the same between starts
        self.resize(800, 600)
        self.move(300, 300)
        self.setWindowTitle('Encuentro')

        self.programs_data = data.ProgramsData(self, self._programs_file)
        self.config = self._load_config()

        self.downloaders = {}
        for downtype, dloader_class in all_downloaders.iteritems():
            self.downloaders[downtype] = dloader_class(self.config)

        # finish all gui stuff
        self._menubar()
        self.big_panel = central_panel.BigPanel(self)
        self.episodes_list = self.big_panel.episodes
        self.episodes_download = self.big_panel.downloads_widget
        self.setCentralWidget(self.big_panel)
        self.show()
        logger.debug("Main UI started ok")

    def _load_config(self):
        """Load the config from disk."""
        # get config from file, or defaults
        if os.path.exists(self._config_file):
            with open(self._config_file) as fh:
                config = pickle.load(fh)
                if self.programs_data.reset_config_from_migration:
                    config['user'] = ''
                    config['password'] = ''
                    config.pop('cols_width', None)
                    config.pop('cols_order', None)
                    config.pop('selected_row', None)
        else:
            config = {}

        # log the config, but without user and pass
        safecfg = config.copy()
        if 'user' in safecfg:
            safecfg['user'] = '<hidden>'
        if 'password' in safecfg:
            safecfg['password'] = '<hidden>'
        logger.debug("Configuration loaded: %s", safecfg)

        # we have a default for download dir
        if not config.get('downloaddir'):
            config['downloaddir'] = platform.get_download_dir()
        return config

    def _have_config(self):
        """Return if some config is needed."""
        return self.config.get('user') and self.config.get('password')

    def _have_metadata(self):
        """Return if metadata is needed."""
        return bool(self.programs_data)

    def _menubar(self):
        """Set up the menu bar."""
        menubar = self.menuBar()

        # applications menu
        menu_appl = menubar.addMenu(u'&Aplicación')

        icon = self.style().standardIcon(QStyle.SP_BrowserReload)
        action_reload = QAction(icon, '&Refrescar', self)
        action_reload.setShortcut('Ctrl+R')
        action_reload.setToolTip(u'Recarga la lista de programas')
        action_reload.triggered.connect(self._refresh_episodes)
        menu_appl.addAction(action_reload)

        # FIXME: set an icon for preferences
        action_preferences = QAction(u'&Preferencias', self)
        action_preferences.triggered.connect(self._preferences)
        action_preferences.setToolTip(
            u'Configurar distintos parámetros del programa')
        menu_appl.addAction(action_preferences)

        menu_appl.addSeparator()

        # FIXME: set an icon for about
        _act = QAction('&Acerca de', self)
        # FIXME: connect signal
        _act.setToolTip(u'Muestra información de la aplicación')
        menu_appl.addAction(_act)

        icon = self.style().standardIcon(QStyle.SP_DialogCloseButton)
        _act = QAction(icon, '&Salir', self)
        _act.setShortcut('Ctrl+Q')
        _act.setToolTip(u'Sale de la aplicación')
        _act.triggered.connect(qApp.quit)
        menu_appl.addAction(_act)

        # program menu
        menu_prog = menubar.addMenu(u'&Programa')

        icon = self.style().standardIcon(QStyle.SP_ArrowDown)
        self.action_download = QAction(icon, '&Descargar', self)
        self.action_download.setShortcut('Ctrl+D')
        self.action_download.setEnabled(False)
        self.action_download.setToolTip(TTIP_DOWNLOAD_D)
        self.action_download.triggered.connect(self.download_episode)
        menu_prog.addAction(self.action_download)

        icon = self.style().standardIcon(QStyle.SP_MediaPlay)
        self.action_play = QAction(icon, '&Reproducir', self)
        self.action_play.setEnabled(False)
        self.action_play.setToolTip(TTIP_PLAY_D)
        self.action_play.triggered.connect(self.play_episode)
        menu_prog.addAction(self.action_play)

        # toolbar for buttons
        toolbar = self.addToolBar('main')
        toolbar.addAction(self.action_download)
        toolbar.addAction(self.action_play)
        toolbar.addSeparator()
        toolbar.addAction(action_reload)
        toolbar.addAction(action_preferences)

        # toolbar for filter
        # FIXME: see if we can put this toolbar to the extreme
        # right of the window
        toolbar = self.addToolBar('')
        toolbar.addWidget(QLabel(u"Filtro: "))
        # FIXME: connect signal
        filter_line = QLineEdit()
        filter_line.textChanged.connect(self.on_filter_changed)
        toolbar.addWidget(filter_line)
        # FIXME: connect signal
        toolbar.addWidget(QCheckBox(u"Sólo descargados"))

        # FIXME: we need to change this text for just a "!" sign image
        self.needsomething_button = QPushButton("Need config!")
        self.needsomething_button.clicked.connect(self._start_wizard)
        toolbar.addWidget(self.needsomething_button)
        if not self.config.get('nowizard'):
            self._start_wizard()
        self._review_need_something_indicator()

    def _start_wizard(self, _=None):
        """Start the wizard if needed."""
        if not self._have_config() or not self._have_metadata():
            dlg = wizard.WizardDialog(self, self._have_config,
                                      self._have_metadata)
            dlg.exec_()
        self._review_need_something_indicator()

    def on_filter_changed(self, new_text):
        """The filter text has changed, apply it in the episodes list."""
        # FIXME: aca no depender de que se recibe, porque el checkbox tambien
        # va a apuntar aca, sino que tomar el texto y el estado del checkbox
        # y llamar a set filter con ambas cosas

        # FIXME: ver que tenemos que normalizar el texto para que la busqueda
        # matchee mejor:
        # text = prepare_to_filter(text)

        # FIXME: en funcion de como ponemos el color resaltado, ver si tenemos
        # que escapar cosas como &:
        # text = cgi.escape(text)

        self.episodes_list.set_filter(new_text)

    def _review_need_something_indicator(self):
        """Hide/show/enable/disable different indicators if need sth."""
        if not self._have_config() or not self._have_metadata():
            # config needed, put the alert if not there
            # FIXME: check this show works ok
            self.needsomething_button.show()
        else:
            # no config needed, remove the alert if there
            # FIXME: this hide() is NOT WORKING!!
            self.needsomething_button.hide()
            # also turn on the download button

    def closeEvent(self, event):
        """All is being closed."""
        if self._should_close():
            # self._save_states()  FIXME: if we need to save states, the call is here
            self.finished = True
            self.programs_data.save()
            for downloader in self.downloaders.itervalues():
                downloader.shutdown()
            self.reactor_stop()
        else:
            event.ignore()

    def _should_close(self):
        """Still time to decide if want to close or not."""
        logger.info("Attempt to close the program")
        pending = self.episodes_download.pending()
        if not pending:
            # all fine, save all and quit
            logger.info("Saving states and quitting")
            return True
        logger.debug("Still %d active downloads when trying to quit", pending)

        # stuff pending
        m = (u"Hay programas todavía en proceso de descarga!\n"
             u"¿Seguro quiere salir del programa?")
        QMB = QMessageBox
        dlg = QMB(u"Guarda!", m, QMB.Question, QMB.Yes, QMB.No, QMB.NoButton)
        opt = dlg.exec_()
        if opt != QMB.Yes:
            logger.info("Quit cancelled")
            return False

        # quit anyway, put all downloading and pending episodes to none
        logger.info("Fixing episodes, saving state and exiting")
        for program in self.programs_data.values():
            state = program.state
            if state == Status.waiting or state == Status.downloading:
                program.state = Status.none
        return True

    def _show_message(self, err_type, text):
        """Show different messages to the user."""
        if self.finished:
            logger.debug("Ignoring message: %r", text)
            return
        logger.debug("Showing a message: %r", text)

        # error text can be produced by windows, try to to sanitize it
        if isinstance(text, str):
            try:
                text = text.decode("utf8")
            except UnicodeDecodeError:
                try:
                    text = text.decode("latin1")
                except UnicodeDecodeError:
                    text = repr(text)

        QMB = QMessageBox
        dlg = QMB(u"Atención: " + err_type, text, QMB.Warning,
                  QMB.Ok, QMB.NoButton, QMB.NoButton)
        dlg.exec_()

    def _refresh_episodes(self, _):
        """Update and refresh episodes."""
        update.UpdateEpisodes(self)

    def download_episode(self, _=None):
        """Download the episode(s)."""
        items = self.episodes_list.selectedItems()
        for item in items:
            episode = self.programs_data[item.episode_id]
            self._queue_download(episode)

    @defer.inlineCallbacks
    def _queue_download(self, episode):
        """User indicated to download something."""
        logger.debug("Download requested of %s", episode)
        if episode.state != Status.none:
            logger.debug("Download denied, episode %s is not in downloadeable "
                         "state.", episode.episode_id)
            return

        # queue
        self.episodes_download.append(episode)
        self.check_download_play_buttons()
        if self.episodes_download.downloading:
            return

        logger.debug("Downloads: starting")
        while self.episodes_download.pending():
            episode = self.episodes_download.prepare()
            try:
                filename, episode = yield self._episode_download(episode)
            except CancelledError:
                logger.debug("Got a CancelledError!")
                self.episodes_download.end(error=u"Cancelao")
            except BadCredentialsError:
                logger.debug("Bad credentials error!")
                msg = (u"Error con las credenciales: hay que configurar "
                       u"usuario y clave correctos")
                self._show_message('BadCredentialsError', msg)
                self.episodes_download.end(error=msg)
            except Exception, e:
                logger.debug("Unknown download error: %s", e)
                err_type = e.__class__.__name__
                self._show_message(err_type, str(e))
                self.episodes_download.end(error=u"Error: " + str(e))
            else:
                logger.debug("Episode downloaded: %s", episode)
                self.episodes_download.end()
                episode.filename = filename

            # check buttons
            self.check_download_play_buttons()

        logger.debug("Downloads: finished")

    @defer.inlineCallbacks
    def _episode_download(self, episode):
        """Effectively download an episode."""
        logger.debug("Effectively downloading episode %s", episode.episode_id)
        self.episodes_download.start()

        # download!
        downloader = self.downloaders[episode.downtype]
        fname = yield downloader.download(episode.channel,
                                          episode.section, episode.title,
                                          episode.url,
                                          self.episodes_download.progress)
        episode_name = u"%s - %s - %s" % (episode.channel, episode.section,
                                          episode.title)
        if self.config.get('notification', True) and pynotify is not None:
            n = pynotify.Notification(u"Descarga finalizada", episode_name)
            n.show()
        defer.returnValue((fname, episode))

    def _preferences(self, _):
        """Open the preferences dialog."""
        dlg = preferences.PreferencesDialog()
        dlg.exec_()
        # FIXME: el dialogo debería grabar solo cuando lo cierran
        dlg.save_config()
        self._review_need_something_indicator()

    def check_download_play_buttons(self):
        """Set both buttons state according to the selected episodes."""
        items = self.episodes_list.selectedItems()
        if not items:
            return

        # 'play' button should be enabled if only one row is selected and
        # its state is 'downloaded'
        play_enabled = False
        if len(items) == 1:
            episode = self.programs_data[items[0].episode_id]
            if episode.state == Status.downloaded:
                play_enabled = True
        self.action_play.setEnabled(play_enabled)
        ttip = TTIP_PLAY_E if play_enabled else TTIP_PLAY_D
        self.action_play.setToolTip(ttip)

        # 'download' button should be enabled if at least one of the selected
        # rows is in 'none' state, and if config is ok
        download_enabled = False
        if self._have_config():
            for item in items:
                episode = self.programs_data[item.episode_id]
                if episode.state == Status.none:
                    download_enabled = True
                    break
        ttip = TTIP_DOWNLOAD_E if download_enabled else TTIP_DOWNLOAD_D
        self.action_download.setEnabled(download_enabled)
        self.action_download.setToolTip(ttip)

    def play_episode(self, _=None):
        """Play the selected episode."""
        items = self.episodes_list.selectedItems()
        if len(items) != 1:
            raise ValueError("Wrong call to play_episode, with %d selections"
                             % len(items))
        item = items[0]
        episode = self.programs_data[item.episode_id]
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
            msg = (u"No se encontró el archivo para reproducir: " +
                   repr(filename))
            self._show_message('Error al reproducir', msg)
            episode.state = Status.none
            episode.color = None

    def cancel_download(self):
        """Cancel the downloading of an episode."""
        items = self.episodes_list.selectedItems()
        if len(items) != 1:
            raise ValueError("Wrong call to cancel_download, with %d "
                             "selections" % len(items))
        item = items[0]
        episode = self.programs_data[item.episode_id]
        logger.info("Cancelling download of %s", episode)
        self.episodes_download.cancel()
        downloader = self.downloaders[episode.downtype]
        downloader.cancel()
