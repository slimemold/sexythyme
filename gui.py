#!/usr/bin/env python3

"""GUI Main Classes

This module contains the top-level Qt GUI classes, such as the main window, the main window's
central widget, status and menu bars, etc.
"""

import csv
import os
from PyQt5.QtCore import QDateTime, QItemSelection, QObject, QRegExp, QSettings, QTime, QTimer, Qt
from PyQt5.QtGui import QKeySequence, QPixmap, QRegExpValidator
from PyQt5.QtWidgets import QFrame, QLabel, QLCDNumber, QLineEdit, QMenuBar, QPushButton, \
                            QShortcut, QStatusBar, QWidget
from PyQt5.QtWidgets import QLayout, QHBoxLayout, QVBoxLayout
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QMessageBox
from PyQt5.QtWidgets import QApplication, QMainWindow
from common import APPLICATION_NAME, VERSION, pluralize, pretty_list
from preferences import PreferencesWindow
from racebuilder import Builder
from racemodel import DatabaseError, ModelDatabase, RaceTableModel
from raceview import FieldTableView, JournalTableView, RacerTableView, ResultTableView
import remotes
from reports import ReportsWindow

__author__ = 'Andrew Chew'
__copyright__ = '''
    Copyright (C) 2018 Andrew Chew

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.
'''
__credits__ = ['Andrew Chew', 'Colleen Chew']
__license__ = 'GPLv3'
__version__ = VERSION
__maintainer__ = 'Andrew Chew'
__email__ = 'andrew@5rcc.com'
__status__ = 'Development'

INPUT_TEXT_POINT_SIZE = 32

# Widget Instance Hierarchy
#
# SexyThymeMainWindow
#     StartCentralWidget
#     MainCentralWidget
#         button_row
#             racer_button
#             field_button
#         clock
#         result_table_view
#         result_input
#         submit_button
#     Builder
#     FieldTableView
#     RacerTableView
#     ResultTableView
#     Preferences
#     RemoteConfig
#     Journal

class AboutDialog(QDialog):
    """About Dialog.

    Should show application name and copyright notice.
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent)

        application_label = QLabel('<h1>' + APPLICATION_NAME + '</h1>')
        application_label.setAlignment(Qt.AlignCenter)

        copyright_label = QLabel(__copyright__)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.setCenterButtons(True)
        button_box.accepted.connect(self.accept)

        self.setLayout(QVBoxLayout())
        self.layout().addWidget(application_label)
        self.layout().addWidget(copyright_label)
        self.layout().addWidget(button_box)
        self.layout().setSizeConstraint(QLayout.SetFixedSize)

class DigitalClock(QLCDNumber):
    """Old-fashioned 7-segment display digital clock showing current time."""
    def __init__(self, parent=None):
        """Initialize the DigitalClock instance."""
        super().__init__(8, parent=parent)

        self.setFrameShape(QFrame.NoFrame)
        self.setSegmentStyle(QLCDNumber.Filled)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.update()
        self.timer.start(100)

        self.setMinimumHeight(48)

    def update(self):
        """Update text on the LCD display."""
        time = QTime.currentTime()

        if time.second() % 2:
            text = time.toString('hh:mm ss')
        else:
            text = time.toString('hh:mm:ss')

        self.display(text)

class CentralWidget(QObject):
    """Central Widget base class.

    Base class for central widgets. Mainly, it has a method has_model() that returns whether a
    race file (the "model") is connected.
    """

    def __init__(self, parent=None):
        """Initialize the CentralWidget instance."""
        super().__init__(parent=parent)

    def has_model(self):
        """Return whether we have a race model loaded.

        Obviously, this base class doesn't support a race model, so we return False.
        """
        return False

class StartCentralWidget(QLabel, CentralWidget):
    """Start Central Widget.

    This is the central widget for when there is no race database currently connected. It just has
    a placeholder graphic. The point is to show something, to give an indication that the app has
    launched, and is waiting to do something useful (like start a new race file, load a race file,
    import a race setup, etc.)
    """

    def __init__(self, parent=None):
        """Initialize the StartCentralWidget instance.

        Just shows a pretty title graphic.
        """
        super().__init__(parent=parent)

        self.setPixmap(QPixmap(os.path.join('resources', 'thyme.jpg')))

class MainCentralWidget(QWidget, CentralWidget):
    """Main Central Widget.

    This is the main race operations window. It presents the results input box, and manages the
    various "floater" windows like racer and field table views.
    """

    def __init__(self, modeldb, parent=None):
        """Initialize the MainCentralWidget instance."""
        super().__init__(parent=parent)

        self.modeldb = modeldb

        self.remote = None

        # Top-level layout. Top to bottom.
        self.setLayout(QVBoxLayout())

        # Button row for race info, field, racer list.
        self.button_row = QWidget()
        self.button_row.setLayout(QHBoxLayout())

        # Race Info, Fields, Racers
        self.button_row.racer_button = QPushButton('Racers')
        self.button_row.racer_button.setCheckable(True)
        self.button_row.racer_button.setToolTip('Toggle racers table')
        self.button_row.field_button = QPushButton('Fields')
        self.button_row.field_button.setCheckable(True)
        self.button_row.field_button.setToolTip('Toggle fields table')
        # Add to button row.
        self.button_row.layout().addWidget(self.button_row.racer_button)
        self.button_row.layout().addWidget(self.button_row.field_button)

        # Digital clock.
        self.digital_clock = DigitalClock()

        # Result table.
        self.result_table_view = ResultTableView(self.modeldb)

        # Result line edit.
        self.result_input = QLineEdit()
        font = self.result_input.font()
        font.setPointSize(INPUT_TEXT_POINT_SIZE)
        self.result_input.setFont(font)
        self.result_input.setValidator(QRegExpValidator(QRegExp('[A-Za-z0-9]*')))

        # Submit button.
        self.submit_button = QPushButton()
        self.submit_button.setToolTip('Submit selected results')
        self.result_selection_changed(QItemSelection(), QItemSelection())

        # Add to top-level layout.
        self.layout().addWidget(self.button_row)
        self.layout().addWidget(self.digital_clock)
        self.layout().addWidget(self.result_table_view)
        self.layout().addWidget(self.result_input)
        self.layout().addWidget(self.submit_button)

        # Floating windows. Keep then hidden initially.
        self.builder = Builder(self.modeldb)
        self.field_table_view = FieldTableView(self.modeldb)
        self.racer_table_view = RacerTableView(self.modeldb)
        self.journal_table_view = JournalTableView(self.modeldb)

        # Try to keep focus on the result input.
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFocusProxy(self.result_input)
        self.return_focus_to_result_input()

        # Signals/slots for button row toggle buttons.
        self.button_row.field_button.toggled.connect(self.field_table_view
                                                         .setVisible)
        self.field_table_view.visibleChanged.connect(self.button_row.field_button
                                                         .setChecked)
        self.button_row.racer_button.toggled.connect(self.racer_table_view
                                                         .setVisible)
        self.racer_table_view.visibleChanged.connect(self.button_row.racer_button
                                                         .setChecked)

        # Signals/slots for field name change notification.
        self.modeldb.field_table_model.dataChanged.connect(self.field_model_changed)

        # Signals/slots for result table.
        self.result_table_view.selectionModel().selectionChanged.connect(
                                                  self.result_selection_changed)
        self.result_table_view.resultDeleted.connect(self.return_focus_to_result_input)

        # Signals/slots for result input.
        self.result_input.returnPressed.connect(self.new_result)

        # Signals/slots for submit button.
        self.submit_button.clicked.connect(self.handle_result_submit)

        # Signals/slots for keyboard shortcuts.
        self.shortcut = QShortcut(QKeySequence('CTRL+S'), self)
        self.shortcut.activated.connect(self.handle_submit_shortcut)

        self.shortcut = QShortcut(QKeySequence('CTRL+R'), self)
        self.shortcut.activated.connect(self.handle_racer_shortcut)

        self.shortcut = QShortcut(QKeySequence('CTRL+F'), self)
        self.shortcut.activated.connect(self.handle_field_shortcut)

        self.shortcut = QShortcut(QKeySequence('CTRL+J'), self)
        self.shortcut.activated.connect(self.handle_journal_shortcut)
        self.shortcut = QShortcut(QKeySequence('CTRL+L'), self)
        self.shortcut.activated.connect(self.handle_journal_shortcut)

    def closeEvent(self, event): #pylint: disable=invalid-name
        """Clean up the MainCentralWidget instance.

        Hide all floater widgets, and cleanup (close) the race model.
        """
        self.builder.hide()
        self.field_table_view.hide()
        self.racer_table_view.hide()
        self.journal_table_view.hide()

        racer_in_field_table_view_dict = self.field_table_view.racer_in_field_table_view_dict
        for _, racer_table_view in racer_in_field_table_view_dict.items():
            racer_table_view.hide()

        self.modeldb.cleanup()
        self.modeldb = None

        super().closeEvent(event)

    def has_model(self):
        """Return whether we have a race model."""
        return self.modeldb is not None

    def field_model_changed(self, top_left, bottom_right, roles):
        """Handle field table model change.

        When someone changes a field name, we have to update the racer model to get the field name
        change. In addition, there is a combo box in the racer table view that is a view for a
        relation model inside the racer model. That combo box needs to update as well, to get the
        field name change.

        Note that we only care if the DisplayRole content changes, and also if the change is in
        the field model's name column.
        """
        if roles and not Qt.DisplayRole in roles:
            return

        field_table_model = self.modeldb.field_table_model
        if not field_table_model.area_contains(top_left, bottom_right,
                                               field_table_model.name_column):
            return

        racer_table_model = self.modeldb.racer_table_model
        field_relation_model = racer_table_model.relationModel(racer_table_model.field_column)

        if not racer_table_model.select():
            raise DatabaseError(racer_table_model.lastError().text())

        if not field_relation_model.select():
            raise DatabaseError(racer_table_model.lastError().text())

    def result_selection_changed(self, selected, deselected):
        """Handle result selection change.

        Change the result submit button depending on selection in the result
        table view.
        """
        del selected, deselected

        selection_count = len(self.result_table_view.selectionModel().selectedRows())
        total_count = self.result_table_view.model().rowCount()

        if selection_count == 0:
            self.submit_button.setText('Submit')
            self.submit_button.setEnabled(False)
        elif selection_count == 1:
            self.submit_button.setText('Submit')
            self.submit_button.setEnabled(True)
        elif selection_count < total_count:
            self.submit_button.setText('Submit Selected')
            self.submit_button.setEnabled(True)
        else:
            self.submit_button.setText('Submit All')
            self.submit_button.setEnabled(True)

    def new_result(self):
        """Handle a new result being entered in the result scratch pad input box."""
        race_table_model = self.modeldb.race_table_model

        scratchpad = self.result_input.text()
        msecs = race_table_model.get_reference_datetime().msecsTo(QDateTime.currentDateTime())
        self.modeldb.result_table_model.add_result(scratchpad, msecs)

        self.result_table_view.scrollToBottom()
        self.result_input.clear()
        self.result_table_view.setFocusProxy(None)

    def handle_result_submit(self):
        """Handle result submit.

        Need to intercept the result submit here so that we can give the input focus back to the
        result input.
        """
        self.result_table_view.handle_submit()
        self.return_focus_to_result_input()

    def return_focus_to_result_input(self):
        """Give focus back to the result input box.

        Also a good time to tweak focus policy and proxies.
        """
        self.result_input.setFocus()

        total_count = self.result_table_view.model().rowCount()
        if total_count:
            self.result_table_view.setFocusProxy(None)
        else:
            self.result_table_view.setFocusProxy(self.result_input)

    def handle_submit_shortcut(self):
        """Handle submit all shortcut.

        If there is no selection, then just try to submit everything in the results list.
        Otherwise, this is basically a shortcut to the submit button.
        """
        if not self.result_table_view.selectedIndexes():
            self.result_table_view.selectAll()

        self.handle_result_submit()

    def handle_racer_shortcut(self):
        """Handle show racer table shortcut."""
        self.button_row.racer_button.click()

    def handle_field_shortcut(self):
        """Handle show field table shortcut."""
        self.button_row.field_button.click()

    def handle_journal_shortcut(self):
        """Handle show journal table shortcut."""
        self.journal_table_view.setVisible(not self.journal_table_view.isVisible())

    def set_remote(self, remote):
        """Do everything needed for a remote that has just been connected."""
        self.remote = remote
        self.racer_table_view.set_remote(remote)

    def connect_preferences(self, preferences):
        """Connect preferences signals to the various slots that care."""
        preferences.digital_clock_checkbox.stateChanged.connect(self.digital_clock.setVisible)
        self.digital_clock.setVisible(preferences.digital_clock_checkbox.checkState())

class SexyThymeMainWindow(QMainWindow):
    """Main Application Window.

    This is the top-level window of the app. Dismissing it closes the app. The window has a
    central widget, which is either the main central widget (when there is a race database
    connected), or the start central widget (when there is no race database currently connected).
    In addition, this main window manages the menu bar, as well as the status bar (when a remote
    is connected, and is used to show remote status).
    """

    def __init__(self, filename=None, parent=None):
        """Initialize the SexyThymeMainWindow instance."""
        super().__init__(parent=parent)

        self.read_settings()

        self.setWindowTitle(APPLICATION_NAME)

        self.setup_menubar()

        self.remote = None

        self.preferences_window = PreferencesWindow()
        self.connect_preferences(self.preferences_window)

        if filename:
            self.switch_to_main(filename)
        else:
            self.switch_to_start()

    def switch_to_start(self):
        """Switch to the StartCentralWidget as our central widget."""
        # Clean up old central widget, which will clean up the model we gave it.
        if self.centralWidget():
            self.centralWidget().close()

        self.setCentralWidget(StartCentralWidget())

        self.generate_reports_menu_action.setEnabled(False)
        self.journal_action.setEnabled(False)
        self.connect_remote_menu.setEnabled(False)
        self.disconnect_remote_menu.setEnabled(False)

    def switch_to_main(self, filename, new=False):
        """Switch to the MainCentralWidget as our central widget."""
        # Clean up old central widget, which will clean up the model we gave it.
        if self.centralWidget():
            self.centralWidget().close()

        # Make a new model, and give it to a new central widget.
        model = ModelDatabase(filename, new)
        self.setCentralWidget(MainCentralWidget(model))

        self.generate_reports_menu_action.setEnabled(True)
        self.journal_action.setEnabled(True)

        remote_class_string = model.race_table_model.get_race_property(RaceTableModel.REMOTE_CLASS)
        if remote_class_string:
            self.connect_remote(remotes.get_remote_class_from_string(remote_class_string))
        else:
            self.set_remote(None)

        self.centralWidget().connect_preferences(self.preferences_window)

    def setup_menubar(self):
        """Set up our menu bar."""
        # Make a parent-less menu bar, so that Qt can use the top-level native
        # one (like on OS-X and Ubuntu Unity) if available.
        menubar = QMenuBar()
        self.setMenuBar(menubar)

        # File menu.
        file_menu = self.menuBar().addMenu('&File')
        file_menu.addAction('New...', self.new_file, QKeySequence.New)
        file_menu.addAction('Open...', self.open_file, QKeySequence.Open)
        file_menu.addAction('Close', self.close_file, QKeySequence.Close)

        file_menu.addSeparator()

        self.generate_reports_menu_action = file_menu.addAction('Generate reports',
                                                                self.generate_reports)

        file_menu.addSeparator()

        file_menu.addAction('Quit', self.close, QKeySequence.Quit)

        # Config menu.
        config_menu = self.menuBar().addMenu('&Config')
        config_menu.addAction('Preferences', self.config_preferences, QKeySequence.Preferences)
        config_menu.addAction('Race Builder', self.config_builder)
        config_menu.addAction('Import Bikereg csv...', self.import_bikereg_file)

        config_menu.addSeparator()

        self.connect_remote_menu = config_menu.addMenu('Connect Remote')
        remote_class_list = remotes.get_remote_class_list()
        for remote_class in remote_class_list:
            receiver = lambda remote_class=remote_class: self.connect_remote(remote_class)
            self.connect_remote_menu.addAction(remote_class.name, receiver)

        self.disconnect_remote_menu = config_menu.addAction('Disconnect Remote',
                                                            self.disconnect_remote)

        help_menu = self.menuBar().addMenu('&Help')
        help_menu.addAction('About', self.help_about)
        self.journal_action = help_menu.addAction('Show Journal', self.help_journal)

    def keyPressEvent(self, event): #pylint: disable=invalid-name
        """Handle key presses."""
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event): #pylint: disable=invalid-name
        """Handle close event.

        If there are unsubmitted results, ask if we really want to close.
        """
        if self.should_close():
            # Clean up old central widget, which will clean up the model we gave it.
            if self.centralWidget():
                self.centralWidget().close()

            self.preferences_window.hide()

            self.write_settings()
            event.accept()

            # This is needed to get all other top-level windows to close as well.
            QApplication.quit()
        else:
            event.ignore()

    def new_file(self):
        """Start a new race file.

        Show a file selection dialog for choosing a new file name (or choose an existing file name
        to overwrite with a new race).
        """
        dialog = QFileDialog(self)
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        dialog.setDefaultSuffix('rce')
        dialog.setFileMode(QFileDialog.AnyFile)
        dialog.setLabelText(QFileDialog.Accept, 'New')
        dialog.setNameFilter('Race file (*.rce)')
        dialog.setOptions(QFileDialog.DontUseNativeDialog)
        dialog.setViewMode(QFileDialog.List)

        if not dialog.exec():
            return None

        filename = dialog.selectedFiles()[0]
        self.switch_to_main(filename, True)
        self.centralWidget().modeldb.add_defaults()

        return filename

    def open_file(self):
        """Open an existing race file.

        Show a file selection dialog for choosing an existing file name to load.
        """
        dialog = QFileDialog(self)
        dialog.setAcceptMode(QFileDialog.AcceptOpen)
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter('Race file (*.rce)')
        dialog.setOptions(QFileDialog.DontUseNativeDialog)
        dialog.setViewMode(QFileDialog.List)

        if not dialog.exec():
            return None

        filename = dialog.selectedFiles()[0]
        self.switch_to_main(filename, False)
        self.centralWidget().modeldb.add_defaults()

        return filename

    def close_file(self):
        """Close the current race.

        This takes us back to the start central widget.
        """
        if self.should_close():
            self.switch_to_start()

    def import_file_prepare(self):
        """Prepare for importing a race file (exported from some other service).

        Need to show a file selection dialog to choose the import file. Then, show another file
        selection dialog to choose where to store the race file (with appropriate warning for
        selecting an existing file).
        """
        # Pick the import file.
        dialog = QFileDialog(self)
        dialog.setAcceptMode(QFileDialog.AcceptOpen)
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter('Bikereg file (*.csv)')
        dialog.setOptions(QFileDialog.DontUseNativeDialog)
        dialog.setViewMode(QFileDialog.List)

        if not dialog.exec():
            return None

        import_filename = dialog.selectedFiles()[0]

        # If we are not yet initialized, pick a new race file.
        if not self.centralWidget().has_model():
            dialog = QFileDialog(self)
            dialog.setAcceptMode(QFileDialog.AcceptSave)
            dialog.setDefaultSuffix('rce')
            dialog.setFileMode(QFileDialog.AnyFile)
            dialog.setLabelText(QFileDialog.Accept, 'New')
            dialog.setNameFilter('Race file (*.rce)')
            dialog.setOptions(QFileDialog.DontUseNativeDialog)
            dialog.setViewMode(QFileDialog.List)

            if dialog.exec():
                filename = dialog.selectedFiles()[0]
                self.switch_to_main(filename, True)
                return import_filename
            else:
                return None

        # Otherwise, if our current race has stuff in it, confirm to overwrite
        # before clearing it.

        # Get Field and Racer tables so we can whine about how much state
        # we're going to lose if we let the import happen.
        field_table_model = self.centralWidget().modeldb.field_table_model
        racer_table_model = self.centralWidget().modeldb.racer_table_model

        if ((field_table_model.rowCount() != 0) or
            (racer_table_model.rowCount() != 0)):
            msg_box = QMessageBox()
            msg_box.setWindowTitle(APPLICATION_NAME)
            msg_box.setText('Overwriting %s!' %
                            pretty_list([pluralize('field', field_table_model.rowCount()),
                                         pluralize('racer', racer_table_model.rowCount())]))
            msg_box.setInformativeText('Do you really want to overwrite ' +
                                       'this data?')
            msg_box.setStandardButtons(QMessageBox.Ok |
                                       QMessageBox.Cancel)
            msg_box.setDefaultButton(QMessageBox.Cancel)
            msg_box.setIcon(QMessageBox.Information)

            if msg_box.exec() != QMessageBox.Ok:
                return None

        # Reuse old filename.
        filename = self.centralWidget().modeldb.filename
        self.switch_to_main(filename, True)

        return import_filename

    def import_bikereg_file(self):
        """Import a BikeReg csv racers list export file.

        This starts a new race and populates the field and racer lists with the stuff from the
        csv file.
        """
        import_filename = self.import_file_prepare()

        if not import_filename:
            return

        with open(import_filename) as import_file:
            reader = csv.reader(import_file)

            # Skip the heading row.
            next(reader)

            for row in reader:
                age, bib, field, _, first_name, _, last_name, _, team, category, *_ = row

                # BikeReg lists One-day License holders twice, and the second
                # listing is missing the bib#, and instead has:
                # "License - 1/1/2018 - One-day License" as the field. Skip over
                # these entries.
                if 'One-day License' in field:
                    continue

                racer_table_model = self.centralWidget().modeldb.racer_table_model

                racer_table_model.add_racer(bib, first_name, last_name, field, category, team, age)

        self.centralWidget().modeldb.add_defaults()

        # Open the racer and field windows so that the import actually looks like it did something.
        self.centralWidget().button_row.racer_button.click()
        self.centralWidget().button_row.field_button.click()

        field_table_model = self.centralWidget().modeldb.field_table_model
        racer_table_model = self.centralWidget().modeldb.racer_table_model

        # Show import summary.
        if ((field_table_model.rowCount() != 0) or
            (racer_table_model.rowCount() != 0)):
            message_text = (('Imported %s. ' %
                             pretty_list([pluralize('field', field_table_model.rowCount()),
                                          pluralize('racer', racer_table_model.rowCount())])) +
                            'Would you like to open the Race Builder to assign start times?')

            msg_box = QMessageBox()
            msg_box.setWindowTitle(APPLICATION_NAME)
            msg_box.setText('Import complete.')

            msg_box.setInformativeText(message_text)
            msg_box.addButton(QMessageBox.Ok)
            msg_box.addButton('Later', QMessageBox.RejectRole)
            msg_box.setDefaultButton(QMessageBox.Ok)
            msg_box.setIcon(QMessageBox.Question)

            if msg_box.exec() == QMessageBox.Ok:
                self.config_builder()
                self.centralWidget().builder.setCurrentIndex(1)

    def generate_reports(self):
        """Show the reports window."""
        dialog = ReportsWindow(self.centralWidget().modeldb, self)
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.show()

    def config_preferences(self):
        """Show the preferences window."""
        self.preferences_window.show()
        self.preferences_window.raise_()

    def config_builder(self):
        """Show the race builder window."""
        self.centralWidget().builder.show()
        self.centralWidget().builder.raise_()

    def connect_remote(self, remote_class):
        """Instantiate the given remote class, and use it to connect to the remote service."""
        remote = remote_class(self.centralWidget().modeldb)
        # Allow remote setup if okay or timed out (but not rejected).
        if remote.connect(self) == remotes.Status.Rejected:
            remote = None

        self.set_remote(remote)

    def disconnect_remote(self):
        """Disconnect the currently connected remote (if any)."""
        if self.remote:
            self.remote.disconnect(self)
        self.set_remote(None)

    def set_remote(self, remote):
        """Do everything needed for a remote that has just been connected."""
        race_table_model = self.centralWidget().modeldb.race_table_model

        if remote:
            race_table_model.set_race_property(RaceTableModel.REMOTE_CLASS, type(remote).__name__)
            self.connect_remote_menu.setEnabled(False)
            self.disconnect_remote_menu.setEnabled(True)
            self.setStatusBar(QStatusBar())
            remote.last_status_changed.connect(self.remote_status_changed)
            self.remote_status_changed(remote.last_status)
        else:
            race_table_model.delete_race_property(RaceTableModel.REMOTE_CLASS)
            self.connect_remote_menu.setEnabled(True)
            self.disconnect_remote_menu.setEnabled(False)
            if self.remote:
                self.remote.last_status_changed.disconnect(self.remote_status_changed)
            self.setStatusBar(None)

        self.remote = remote
        self.centralWidget().set_remote(remote)

    def remote_status_changed(self, status):
        """Handle remote status change.

        This amounts to changing the text in the status bar.
        """
        if status == remotes.Status.Ok:
            self.statusBar().showMessage('Remote: Ok')
        elif status == remotes.Status.TimedOut:
            self.statusBar().showMessage('Remote: Timed Out')
        elif status == remotes.Status.Rejected:
            self.statusBar().showMessage('Remote: Rejected')
        else:
            self.statusBar().showMessage('Remote: Unknown State')

    def help_about(self):
        """Show about dialog."""
        AboutDialog(self).show()

    def help_journal(self):
        """Show about dialog."""
        self.centralWidget().journal_table_view.show()

    def should_close(self):
        """Ask user if we really want to close the app."""
        # If there are unsubmitted results, give the user a chance to cancel
        # the quit...not that the user will lose anything, but just as a heads
        # up that there's unfinished business on the part of the user.
        if (self.centralWidget().has_model() and
            (self.centralWidget().result_table_view.model().rowCount() != 0)):
            msg_box = QMessageBox()
            msg_box.setWindowTitle(APPLICATION_NAME)
            msg_box.setText('You have unsubmitted results.')
            msg_box.setInformativeText('Do you really want to quit?')
            msg_box.setStandardButtons(QMessageBox.Ok |
                                       QMessageBox.Cancel)
            msg_box.setDefaultButton(QMessageBox.Cancel)
            msg_box.setIcon(QMessageBox.Information)

            return msg_box.exec() == QMessageBox.Ok

        return True

    def set_window_flag_stays_on_top(self, state):
        """Change the Qt.WindowStaysOnTop window flag.

        Couldn't use a lambda for this since I have to show() afterwards.
        Still, there's issues with this...it doesn't really work. Supposedly,
        worked in Qt4, so this is a regression.
        """
        self.setWindowFlag(Qt.WindowStaysOnTopHint, state)
        self.show()

    def connect_preferences(self, preferences):
        """Connect preferences signals to the various slots that care."""
        preferences.always_on_top_checkbox.stateChanged.connect(self.set_window_flag_stays_on_top)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, preferences.always_on_top_checkbox.checkState())

    def read_settings(self):
        """Read settings."""
        group_name = self.__class__.__name__
        settings = QSettings()
        settings.beginGroup(group_name)

        if settings.contains('size'):
            self.resize(settings.value('size'))
        if settings.contains('pos'):
            self.move(settings.value('pos'))

        settings.endGroup()

    def write_settings(self):
        """Write settings."""
        group_name = self.__class__.__name__
        settings = QSettings()
        settings.beginGroup(group_name)

        settings.setValue('size', self.size())
        settings.setValue('pos', self.pos())

        settings.endGroup()
