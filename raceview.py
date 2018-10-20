import csv
import os
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from common import *
from racemodel import *

CONST_INPUT_TEXT_POINT_SIZE = 32
CONST_RESULT_TABLE_POINT_SIZE = 20

class RaceInfo(QTableView):
    def __init__(self, race_model, parent=None):
        super().__init__(parent=parent)

        self.setModel(race_model)

        self.setWindowTitle('Race Info')

        # Set up our view.
        self.setItemDelegate(QSqlRelationalDelegate())
        self.horizontalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setHighlightSections(False)
        self.verticalHeader().setVisible(False)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.visibleChanged.emit(False)

    # Signals.
    visibleChanged = pyqtSignal(bool)

class FieldProxyModel(QIdentityProxyModel):
    def columnCount(self, parent):
        return self.sourceModel().columnCount(parent) + 2

    def fieldIndex(self, field_name):
        return self.sourceModel().fieldIndex(field_name)

    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if section == 3:
                return 'Finished'
            elif section == 4:
                return 'Total'

        return self.sourceModel().headerData(section, orientation, role)

    def __normalizedSection(self, section):
        return section - self.sourceModel().columnCount(parent)

class FieldTable(QTableView):
    def __init__(self, field_model, parent=None):
        super().__init__(parent=parent)

        self.setModel(field_model)
        self.setupProxyModel()

        self.setWindowTitle('Fields')

        # Set up our view.
        self.setItemDelegate(QSqlRelationalDelegate())
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True) # Allow sorting by column
        self.setSelectionBehavior(QTableView.SelectRows)
        self.sortByColumn(self.model().fieldIndex('name'),
                          Qt.SortOrder.AscendingOrder)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setVisible(False)
        self.hideColumn(self.model().fieldIndex('id'))
        self.hideColumn(self.model().fieldIndex('data'))

    def setupProxyModel(self):
        # Use a proxy model so we can add some interesting columns.
        proxyModel = FieldProxyModel()
        proxyModel.setSourceModel(self.model())

        self.setModel(proxyModel)

        self.model().setHeaderData(1, Qt.Horizontal, 'Field')
        self.model().setHeaderData(4, Qt.Horizontal, 'Finished')
        self.model().setHeaderData(5, Qt.Horizontal, 'Total')

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.visibleChanged.emit(False)

    # Signals.
    visibleChanged = pyqtSignal(bool)

class RacerTable(QTableView):
    def __init__(self, racer_model, parent=None):
        super().__init__(parent=parent)

        self.setModel(racer_model)

        self.setWindowTitle('Racers')

        # Set up our view.
        self.setItemDelegate(QSqlRelationalDelegate())
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True) # Allow sorting by column
        self.setSelectionBehavior(QTableView.SelectRows)
        self.sortByColumn(self.model().fieldIndex('bib'),
                          Qt.SortOrder.AscendingOrder)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setVisible(False)
        self.hideColumn(self.model().fieldIndex('id'))
        self.hideColumn(self.model().fieldIndex('data'))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.visibleChanged.emit(False)

    # Signals.
    visibleChanged = pyqtSignal(bool)

class ResultTable(QTableView):
    def __init__(self, result_model, parent=None):
        super().__init__(parent=parent)

        self.setModel(result_model)

        self.setItemDelegate(QSqlRelationalDelegate())
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(False) # Don't allow sorting.
        self.setSelectionBehavior(QTableView.SelectRows)
        self.sortByColumn(self.model().fieldIndex('id'),
                          Qt.SortOrder.AscendingOrder)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setVisible(False)
        self.hideColumn(self.model().fieldIndex('id'))
        self.hideColumn(self.model().fieldIndex('data'))

        font = self.font()
        font.setPointSize(CONST_RESULT_TABLE_POINT_SIZE)
        self.setFont(font)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Backspace:
            self.handleDelete()

        return super().keyPressEvent(event)

    def handleDelete(self):
        model = self.selectionModel().model()
        selection_list = self.selectionModel().selectedRows()
        for selection in selection_list:
            record = model.record(selection.row())
            bib = record.value('scratchpad')
            finish = record.value('finish')

class CentralWidget(QObject):
    def __init__(self, parent=None):
        super().__init__(parent=parent)

    def cleanup(self):
        pass

    def hasModel(self):
        return False

class MainWidget(QWidget, CentralWidget):
    def __init__(self, modeldb, parent=None):
        super().__init__(parent=parent)

        self.modeldb = modeldb

        # Top-level layout. Top to bottom.
        self.setLayout(QVBoxLayout())

        # Button row for race info, field, racer list.
        self.button_row = QWidget()
        self.button_row.setLayout(QHBoxLayout())

        # Race Info, Fields, Racers
        self.button_row.race_button = QPushButton('Race Info')
        self.button_row.race_button.setCheckable(True)
        self.button_row.field_button = QPushButton('Fields')
        self.button_row.field_button.setCheckable(True)
        self.button_row.racer_button = QPushButton('Racers')
        self.button_row.racer_button.setCheckable(True)

        # Add to button row.
        self.button_row.layout().addWidget(self.button_row.race_button)
        self.button_row.layout().addWidget(self.button_row.field_button)
        self.button_row.layout().addWidget(self.button_row.racer_button)

        # Result table.
        self.result_table = ResultTable(self.modeldb.result_table_model)

        # Result line edit.
        self.result_input = QLineEdit()
        self.result_input.setClearButtonEnabled(True)
        font = self.result_input.font()
        font.setPointSize(CONST_INPUT_TEXT_POINT_SIZE)
        self.result_input.setFont(font)

        # Commit button.
        self.commit_button = QPushButton('Commit Selected')

        # Add to top-level layout.
        self.layout().addWidget(self.button_row)
        self.layout().addWidget(self.result_table)
        self.layout().addWidget(self.result_input)
        self.layout().addWidget(self.commit_button)

        # Floating windows. Keep then hidden initially.
        self.race_info = RaceInfo(self.modeldb.race_table_model)
        self.field_table = FieldTable(self.modeldb.field_table_model)
        self.racer_table = RacerTable(self.modeldb.racer_table_model)

        # Signals/slots for button row toggle buttons.
        self.button_row.race_button.toggled.connect(self.race_info
                                                        .setVisible)
        self.race_info.visibleChanged.connect(self.button_row.race_button
                                                  .setChecked)
        self.button_row.field_button.toggled.connect(self.field_table
                                                         .setVisible)
        self.field_table.visibleChanged.connect(self.button_row.field_button
                                                    .setChecked)
        self.button_row.racer_button.toggled.connect(self.racer_table
                                                         .setVisible)
        self.racer_table.visibleChanged.connect(self.button_row.racer_button
                                                    .setChecked)

        # Signals/slots for field name change notification.
        self.modeldb.field_table_model.dataChanged.connect(
                                                       self.fieldModelChanged)

        # Signals/slots for result input.
        self.result_input.returnPressed.connect(self.newResult)

        # Signals/slots for commit button.
        self.commit_button.clicked.connect(self.commitResults)

    def cleanup(self):
        self.modeldb.cleanup()
        self.modeldb = None

    def hasModel(self):
        return self.modeldb is not None

    def fieldModelChanged(self, top_left, bottom_right, roles):
        # When someone changes a field name, we have to update the racer model
        # to get the field name change. In addition, there is a combo box
        # in the racer table view that is a view for a relation model inside
        # the racer model. That combo box needs to update as well, to get the
        # field name change.
        racer_table_model = self.modeldb.racer_table_model
        field_relation_model = racer_table_model.relationModel(
                                   racer_table_model.fieldIndex('field_name_2'))

        racer_table_model.select()
        field_relation_model.select()

    def newResult(self):
        self.modeldb.addResult(self.result_input.text(), QTime.currentTime())
        self.result_table.scrollToBottom()
        self.result_input.clear()

    def commitResults(self):
        print('commitResults')

class DummyWidget(QLabel, CentralWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)

        self.setPixmap(QPixmap(os.path.join('resources', 'thyme.jpg')))

class SexyThymeMainWindow(QMainWindow):
    def __init__(self, filename=None, parent=None):
        super().__init__(parent=parent)

        self.setWindowTitle(CONST_APPLICATION_NAME)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        self.setupMenuBar()

        if filename:
            self.switchToMain(filename)
        else:
            self.switchToDummy()

    def switchToDummy(self):
        # Clean up old central widget, which will clean up the model we gave it.
        if self.centralWidget():
            self.centralWidget().cleanup()

        self.setCentralWidget(DummyWidget())

    def switchToMain(self, filename, new=False):
        # Clean up old central widget, which will clean up the model we gave it.
        if self.centralWidget():
            self.centralWidget().cleanup()

        # Make a new model, and give it to a new central widget.
        model = ModelDatabase(filename, new)
        self.setCentralWidget(MainWidget(model))

    def setupMenuBar(self):
        self.menuBar().setNativeMenuBar(False)
        fileMenu = self.menuBar().addMenu('&File');
        fileMenu.addAction('New...', self.newFile, QKeySequence.New)
        fileMenu.addAction('Open...', self.openFile, QKeySequence.Open)
        fileMenu.addSeparator()
        fileMenu.addAction('Import Bikereg csv', self.importBikeregFile)
        fileMenu.addSeparator()
        fileMenu.addAction('Quit', self.close, QKeySequence.Quit)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if (not self.centralWidget().hasModel() or
            (self.centralWidget().result_table.model().rowCount() == 0)):
            event.accept()
            QApplication.quit()
            return

        msg_box = QMessageBox()
        msg_box.setWindowTitle(CONST_APPLICATION_NAME)
        msg_box.setText('You have uncommitted results.')
        msg_box.setInformativeText('Do you really want to quit?')
        msg_box.setStandardButtons(QMessageBox.Ok |
                                   QMessageBox.Cancel)
        msg_box.setDefaultButton(QMessageBox.Cancel)
        msg_box.setIcon(QMessageBox.Information)

        if msg_box.exec() == QMessageBox.Ok:
            event.accept()
            QApplication.quit()
        else:
            event.ignore()

    def newFile(self):
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
        self.switchToMain(filename, True)

        return filename

    def openFile(self):
        dialog = QFileDialog(self)
        dialog.setAcceptMode(QFileDialog.AcceptOpen)
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter('Race file (*.rce)')
        dialog.setOptions(QFileDialog.DontUseNativeDialog)
        dialog.setViewMode(QFileDialog.List)

        if not dialog.exec():
            return None

        filename = dialog.selectedFiles()[0]
        self.switchToMain(filename, False)

        return filename

    def importFilePrepare(self):
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
        if not self.centralWidget().hasModel():
            if self.newFile():
                return import_filename
            else:
                return None

        # Otherwise, if our current race has stuff in it, confirm to overwrite
        # before clearing it.

        # Get Field and Racer tables so we can whine about how much state
        # we're going to lose if we let the import happen.
        field_model = self.centralWidget().field_table.model()
        racer_model = self.centralWidget().racer_table.model()

        if (field_model.rowCount() != 0) or (racer_model.rowCount() != 0):
            msg_box = QMessageBox()
            msg_box.setWindowTitle(CONST_APPLICATION_NAME)
            msg_box.setText('There are %s fields and %s racers defined.' %
                            (field_model.rowCount(), racer_model.rowCount()))
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
        self.switchToMain(filename, True)

        return import_filename

    def importBikeregFile(self):
        import_filename = self.importFilePrepare()

        if not import_filename:
            return

        with open(import_filename) as import_file:
            reader = csv.reader(import_file)

            # Skip the heading row.
            next(reader)

            for row in reader:
                _, bib, field, _, first_name, _, last_name, _, team, *_ = row
                name = first_name + ' ' + last_name

                # BikeReg lists One-day License holders twice, and the second
                # listing is missing the bib#, and instead has:
                # "License - 1/1/2018 - One-day License" as the field. Skip over
                # these entries.
                if 'One-day License' in field:
                    continue

                racer_table_model = self.centralWidget().modeldb.racer_table_model

                racer_table_model.addRacer(bib, name, team, field,
                                           QTime.currentTime(),
                                           QTime.currentTime())
