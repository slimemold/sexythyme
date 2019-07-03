#!/usr/bin/env python3

"""SQL Table View Classes

This module contains the various Qt SQL Table Views (field table view, racer table views,
result scratch pad table view), as well as whatever proxy models are stacked between the views
and the models.
"""

import os
from PyQt5.QtCore import QEvent, QItemSelection, QModelIndex, QRegExp, QSettings, \
                         QSortFilterProxyModel, Qt, pyqtSignal
from PyQt5.QtWidgets import QDialog, QLabel, QMessageBox, QStyledItemDelegate, QTableView, \
                            QVBoxLayout
import common
import defaults
from delegates import SqlRelationalDelegate
from proxymodels import ExtraColumnsProxyModel, MSecsColumnsProxyModel
from racemodel import InputError, FieldTableModel, Journal, ResultTableModel
from racemodel import msecs_is_valid, MSECS_UNINITIALIZED

__copyright__ = '''
    Copyright (C) 2018-2019 Andrew Chew

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
__author__ = common.AUTHOR
__credits__ = common.CREDITS
__license__ = common.LICENSE
__version__ = common.VERSION
__maintainer__ = common.MAINTAINER
__email__ = common.EMAIL
__status__ = common.STATUS

class ReadOnlyStyledItemDelegate(QStyledItemDelegate):
    """Item delegate that makes a view read-only."""
    def createEditor(self, parent, option, index): #pylint: disable=invalid-name
        """Never return any editors, making the item read-only."""
        del parent
        del option
        del index

class JournalTableView(QTableView):
    """Table view for the journal table model."""

    def __init__(self, modeldb, parent=None):
        """Initialize the JournalTableView instance."""
        super().__init__(parent=parent)

        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.modeldb = modeldb

        self.source_model = self.modeldb.journal_table_model
        self.setModel(self.source_model)

        self.setWindowTitle('Journal')

        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.setSelectionBehavior(QTableView.SelectRows)
        self.sortByColumn(self.source_model.timestamp_column, Qt.DescendingOrder)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionsMovable(True)
        self.verticalHeader().setVisible(False)
        self.hideColumn(self.source_model.id_column)

        # Make this table view read-only.
        self.setItemDelegate(ReadOnlyStyledItemDelegate())

        self.read_settings()

    def hideEvent(self, event): #pylint: disable=invalid-name
        """Handle hide event."""
        del event
        self.write_settings()
        self.visibleChanged.emit(False)

    def read_settings(self):
        """Read settings."""
        group_name = self.__class__.__name__
        settings = QSettings()
        settings.beginGroup(group_name)

        self.resize(settings.value('size', defaults.JOURNAL_TABLE_VIEW_SIZE))

        if settings.contains('pos'):
            self.move(settings.value('pos'))

        if settings.contains('horizontal_header_state'):
            self.horizontalHeader().restoreState(settings.value('horizontal_header_state'))

        settings.endGroup()

    def write_settings(self):
        """Write settings."""
        group_name = self.__class__.__name__
        settings = QSettings()
        settings.beginGroup(group_name)

        settings.setValue('size', self.size())
        settings.setValue('pos', self.pos())
        settings.setValue('horizontal_header_state', self.horizontalHeader().saveState())

        settings.endGroup()

    # Signals.
    visibleChanged = pyqtSignal(bool)

# Add a "Finished" column for total racers that have a finish time, and a
# "Total" column to show total racers in that field.
class FieldProxyModel(ExtraColumnsProxyModel):
    """Proxy model for the field table model.

    This proxy model adds extra columns to the field table. Extra columns include number of racers
    finished, number of racers total, and completion status.
    """

    FINISHED_SECTION = 0
    TOTAL_SECTION = 1
    STATUS_SECTION = 2

    def __init__(self, parent=None):
        """Initialize the FieldProxyModel instance."""
        super().__init__(parent=parent)

        self.appendColumn('Finished')
        self.appendColumn('Total')
        self.appendColumn('Status')

    def extraColumnData(self, parent, row, extra_column, role=Qt.DisplayRole):
        """Provide extra columns for racers finished, total racers, and field status."""
        if role == Qt.DisplayRole:
            field_table_model = self.sourceModel()
            racer_table_model = self.sourceModel().modeldb.racer_table_model

            field_name = field_table_model.record(row).value(FieldTableModel.NAME)

            total = racer_table_model.racer_count_total_in_field(field_name)
            finished = racer_table_model.racer_count_finished_in_field(field_name)

            if extra_column == self.FINISHED_SECTION:
                return finished
            elif extra_column == self.TOTAL_SECTION:
                return total
            elif extra_column == self.STATUS_SECTION:
                if total == 0:
                    return 'Empty'
                elif finished < total:
                    return 'In Progress (%s%%)' % int(round(finished * 100 / total))
                else:
                    return 'Complete'

        return None

class FieldTableView(QTableView):
    """Table view for the field table model."""

    def __init__(self, modeldb, parent=None):
        """Initialize the FieldTableView instance."""
        super().__init__(parent=parent)

        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.modeldb = modeldb
        self.remote = None
        self.preferences = None

        """Use a proxy model so we can add some interesting columns."""
        self.source_model = self.modeldb.field_table_model
        self.proxy_model = FieldProxyModel(parent=parent)
        self.proxy_model.setSourceModel(self.source_model)
        self.setModel(self.proxy_model)

        self.setWindowTitle('Fields')

        # Set up our view.
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True) # Allow sorting by column
        self.setSelectionBehavior(QTableView.SelectRows)
        self.sortByColumn(self.source_model.name_column, Qt.AscendingOrder)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionsMovable(True)
        self.verticalHeader().setVisible(False)

        # For each field, we make a racer in field table view ahead of time.
        # Note that we call dataChanged here because the initial reading of
        # the model is not considered a data change, but we need to do this
        # anyway to populate racer_in_field_table_view_dict.
        self.racer_in_field_table_view_dict = {}
        self.dataChanged(QModelIndex(), QModelIndex(), [])

        # Signals/slots to handle racer in field table views.
        self.modeldb.racer_table_model.dataChanged.connect(self.update_non_model_columns)
        self.doubleClicked.connect(self.handle_show_racer_in_field_table_view)

        self.read_settings()

        # Always hide id, metadata column.
        self.hideColumn(self.source_model.id_column)
        self.hideColumn(self.source_model.metadata_column)

    def keyPressEvent(self, event): #pylint: disable=invalid-name
        """Handle key presses."""
        if event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() == Qt.Key_Backspace or event.key() == Qt.Key_Delete:
            self.handle_delete()

        return super().keyPressEvent(event)

    def hideEvent(self, event): #pylint: disable=invalid-name
        """Handle hide event."""
        del event
        self.write_settings()
        self.visibleChanged.emit(False)

    def handle_delete(self):
        """Handle delete key press.

        On delete key press, delete the selection.
        """
        model = self.selectionModel().model()
        selection_list = self.selectionModel().selectedRows()

        field_table_model = self.modeldb.field_table_model
        racer_table_model = self.modeldb.racer_table_model

        field_count = len(selection_list)
        racer_count = 0
        for selection in selection_list:
            field_record = field_table_model.record(selection.row())
            field_id = field_record.value(FieldTableModel.ID)

            racer_count += racer_table_model.racer_count_total_in_field(field_id)

        # Confirm deletion.
        msg_box = QMessageBox()
        msg_box.setWindowTitle(common.APPLICATION_NAME)
        msg_box.setText('Deleting %s' %
                        common.pretty_list([common.pluralize('field', field_count),
                                            common.pluralize('racer', racer_count)]))
        msg_box.setInformativeText('Do you really want to delete?')
        msg_box.setStandardButtons(QMessageBox.Ok |
                                   QMessageBox.Cancel)
        msg_box.setDefaultButton(QMessageBox.Cancel)
        msg_box.setIcon(QMessageBox.Information)

        if msg_box.exec() != QMessageBox.Ok:
            return

        # Remove rows from large to small, because the rows are removed
        # immediately, and cause the rest of the rows to shift, invalidating
        # any row number that's higher than the currently removed one.
        selection_list.sort(key=lambda selection: selection.row(), reverse=True)
        for selection in selection_list:
            field_record = field_table_model.record(selection.row())
            field_id = field_record.value(FieldTableModel.ID)

            racer_in_field_table_view = self.racer_in_field_table_view_dict[field_id]
            racer_in_field_table_model = racer_in_field_table_view.model()

            # Have to remove one row at a time from the proxy model. For some
            # reason, a ranged removeRows() fails.
            # Also, the removal is immediate, so we keep removing index 0.
            for row in reversed(range(racer_in_field_table_model.rowCount())):
                racer_in_field_table_model.removeRow(row)

            model.removeRow(selection.row())

        # Model retains blank rows until we select() again.
        self.modeldb.field_table_model.select()

    def dataChanged(self, top_left, bottom_right, roles): #pylint: disable=invalid-name
        """Handle model data changed.

        One big thing we need to do here is make new field-specific racer table views (or remove
        existing ones) if a field was added, renamed, or removed. We basically keep a dictionary
        of field_id:racer_table_view of all field-specific racer table views, and in this method,
        we scan through the list of fields and update this dictionary accordingly.
        """
        super().dataChanged(top_left, bottom_right, roles)

        field_table_model = self.modeldb.field_table_model

        # When roles is empty, it means everything has changed
        if roles and not Qt.DisplayRole in roles:
            return

        if (top_left.isValid() and
            (top_left.column() > field_table_model.name_column)):
            return

        # Field table model changed. Go through the model to see if we need to
        # make any new racer-in-field-table-views. Drop the ones we don't
        # need anymore.
        new_racer_table_view_dict = {}

        for row in range(field_table_model.rowCount()):
            record = field_table_model.record(row)
            field_id = record.value(FieldTableModel.ID)
            if field_id in self.racer_in_field_table_view_dict:
                new_racer_table_view_dict[field_id] = self.racer_in_field_table_view_dict[field_id]
                new_racer_table_view_dict[field_id].update_field_name()
            else:
                new_racer_table_view_dict[field_id] = RacerTableView(self.modeldb, field_id)
                new_racer_table_view_dict[field_id].set_remote(self.remote)
                new_racer_table_view_dict[field_id].connect_preferences(self.preferences)

        self.racer_in_field_table_view_dict = new_racer_table_view_dict

    def handle_show_racer_in_field_table_view(self, model_index):
        """Handle activation of a field row.

        On activation of a field row, we show its field-specific racer table view.
        """
        field_table_model = self.modeldb.field_table_model

        # Don't allow using the first two columns to pop up the racer in field
        # table view, because it's likely the user just wants to edit the
        # field name.
        if (model_index.column() == field_table_model.name_column or
            model_index.column() == field_table_model.subfields_column):
            return

        field_id = field_table_model.record(model_index.row()).value(FieldTableModel.ID)

        self.racer_in_field_table_view_dict[field_id].show()

        self.clearSelection()

    def update_non_model_columns(self, top_left, bottom_right, roles):
        """Handle racer table model change.

        On racer table model change, we tickle our dataChanged() slot to induce this table view
        to take another look at the extra columns, since the values in these extra columns depends
        on racer state.

        Our non-model columns (provided by FieldProxyModel(ExtraColumnsProxyModel)) uses stuff from
        the racer table model to provide its contents. Therefore, when the racer model changes, we
        need to pretend our model changed.

        Note that we only care if the role being changed is DisplayRole, and only if the column
        changed is the finish time, or a racer was added/removed. In practice, we can just care
        about the column.  If a racer was added or removed, the finish time column of that racer
        will certainly be changed.
        """
        if roles and not Qt.DisplayRole in roles:
            return

        racer_table_model = self.modeldb.racer_table_model
        if not racer_table_model.area_contains(top_left, bottom_right,
                                               racer_table_model.finish_column):
            return

        field_proxy_model = self.model()

        row_start = 0
        row_end = field_proxy_model.rowCount() - 1
        column_start = field_proxy_model.proxyColumnForExtraColumn(0)
        extra_column_count = field_proxy_model.extraColumnCount()
        column_end = field_proxy_model.proxyColumnForExtraColumn(extra_column_count - 1)

        top_left = self.model().index(row_start, column_start, QModelIndex())
        bottom_right = self.model().index(row_end, column_end, QModelIndex())

        self.dataChanged(top_left, bottom_right, [Qt.DisplayRole])

    def set_remote(self, remote):
        """Call set_remote() for each of our racer-in-field table views."""
        self.remote = remote

        for _, racer_in_field_table_view in self.racer_in_field_table_view_dict.items():
            racer_in_field_table_view.set_remote(remote)

    def connect_preferences(self, preferences):
        """Connect preferences signals to the various slots that care."""
        self.preferences = preferences

        for racer_table_view in self.racer_in_field_table_view_dict.values():
            racer_table_view.connect_preferences(preferences)

    def read_settings(self):
        """Read settings."""
        group_name = self.__class__.__name__
        settings = QSettings()
        settings.beginGroup(group_name)

        self.resize(settings.value('size', defaults.FIELD_TABLE_VIEW_SIZE))
        if settings.contains('pos'):
            self.move(settings.value('pos'))

        if settings.contains('horizontal_header_state'):
            self.horizontalHeader().restoreState(settings.value('horizontal_header_state'))

        settings.endGroup()

    def write_settings(self):
        """Write settings."""
        group_name = self.__class__.__name__
        settings = QSettings()
        settings.beginGroup(group_name)

        settings.setValue('size', self.size())
        settings.setValue('pos', self.pos())
        settings.setValue('horizontal_header_state', self.horizontalHeader().saveState())

        settings.endGroup()

    # Signals.
    visibleChanged = pyqtSignal(bool)

class RacerTableExtraColumnsProxyModel(ExtraColumnsProxyModel):
    """Proxy model for adding columns to the racer table model.

    This proxy model adds extra columns to the racer table. Extra columns include time delta
    (between finish and start)...and that's all for now.
    """

    DELTA_SECTION = 0

    def __init__(self, modeldb, parent=None):
        """Initialize the RacerTableExtraColumnsProxyModel instance."""
        super().__init__(parent=parent)

        # Need the racer model (our source model) to look up start and finish times.
        # Don't want to rely on our source model to actually be the racer model. It could be
        # a proxy model.
        self.modeldb = modeldb

        self.appendColumn('Delta')

    def extraColumnData(self, parent, row, extra_column, role=Qt.DisplayRole):
        """Provide extra columns for delta."""
        if role in (Qt.DisplayRole, Qt.EditRole):
            if extra_column == self.DELTA_SECTION:
                model = self.sourceModel()

                start = model.data(model.index(row, model.start_column))
                if not msecs_is_valid(start):
                    return MSECS_UNINITIALIZED

                finish = model.data(model.index(row, model.finish_column))
                if not msecs_is_valid(finish):
                    return finish

                return finish - start
            else:
                raise IndexError('Unknown extra column number %s' % extra_column)

        # Make the rest of our data (background, etc.) the same as the finish column.
        else:
            model = self.modeldb.racer_table_model

            return model.data(model.index(row, model.finish_column), role)

    def setExtraColumnData(self, parent, row, extra_column, data, role):
        """Set extra column data."""
        if role == Qt.EditRole:
            if extra_column == self.DELTA_SECTION:
                model = self.sourceModel()

                # Use our new delta value to modify the finish time. Our delta column will
                # automatically recalculate.
                start = model.data(model.index(row, model.start_column))
                model.setData(model.index(row, model.finish_column), start + data)

        return False

    def flags(self, index):
        """Make the Delta column editable."""
        extra_col = self.extraColumnForProxyColumn(index.column())
        if extra_col == self.DELTA_SECTION:
            return Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable

        return super().flags(index)

class RacerTableView(QTableView):
    """Table view for the racer table model."""

    def __init__(self, modeldb, field_id=None, parent=None):
        """Initialize the RacerTableView instance."""
        super().__init__(parent=parent)

        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.modeldb = modeldb
        self.remote = None

        self.source_model = self.modeldb.racer_table_model

        # Proxy model to add some columns.
        self.proxy_model_extra_columns = RacerTableExtraColumnsProxyModel(self.modeldb,
                                                                          parent=parent)
        self.proxy_model_extra_columns.setSourceModel(self.source_model)

        # Proxy model to present the time fields in our preferred format.
        self.proxy_model_msecs = MSecsColumnsProxyModel(self.modeldb, parent=parent)
        delta_column = (self.source_model.columnCount() +
                        RacerTableExtraColumnsProxyModel.DELTA_SECTION)
        self.proxy_model_msecs.setMSecsFromReferenceColumns([self.source_model.start_column,
                                                             self.source_model.finish_column])
        self.proxy_model_msecs.setMSecsDeltaColumns([delta_column])
        self.proxy_model_msecs.setSourceModel(self.proxy_model_extra_columns)

        # Proxy model to potentially filter by field.
        self.proxy_model_filter = QSortFilterProxyModel(parent=parent)
        self.proxy_model_filter.setSourceModel(self.proxy_model_msecs)
        self.setModel(self.proxy_model_filter)

        self.field_id = field_id
        self.update_field_name()

        # Set up our view.
        self.setItemDelegateForColumn(self.source_model.field_column, SqlRelationalDelegate())
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True) # Allow sorting by column
        self.setSelectionBehavior(QTableView.SelectRows)
        self.sortByColumn(self.source_model.bib_column, Qt.AscendingOrder)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionsMovable(True)
        self.verticalHeader().setVisible(False)
        # Only hide field column if this table view is for a particular field.
        if self.field_id:
            self.proxy_model_filter.setFilterKeyColumn(self.source_model.field_column)
            self.hideColumn(self.source_model.field_column)

        self.read_settings()

        # Hide the status by default. Show it if we have a remote
        # set up for this race.
        self.hideColumn(self.source_model.status_column)
        # Always hide id, metadata column.
        self.hideColumn(self.source_model.id_column)
        self.hideColumn(self.source_model.metadata_column)

    def keyPressEvent(self, event): #pylint: disable=invalid-name
        """Handle key presses."""
        if event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() == Qt.Key_Backspace or event.key() == Qt.Key_Delete:
            self.handle_delete()

        super().keyPressEvent(event)

    def hideEvent(self, event): #pylint: disable=invalid-name
        """Handle hide event."""
        del event
        self.write_settings()
        self.visibleChanged.emit(False)

    def handle_delete(self):
        """Handle delete key press.

        On delete key press, delete the selection.
        """
        model = self.selectionModel().model()
        selection_list = self.selectionModel().selectedRows()

        racer_count = len(selection_list)

        # Confirm deletion.
        msg_box = QMessageBox()
        msg_box.setWindowTitle(common.APPLICATION_NAME)
        msg_box.setText('Deleting %s' % common.pluralize('racer', racer_count))
        msg_box.setInformativeText('Do you really want to delete?')
        msg_box.setStandardButtons(QMessageBox.Ok |
                                   QMessageBox.Cancel)
        msg_box.setDefaultButton(QMessageBox.Cancel)
        msg_box.setIcon(QMessageBox.Information)

        if msg_box.exec() != QMessageBox.Ok:
            return

        # Remove rows from large to small, because the rows are removed
        # immediately, and cause the rest of the rows to shift, invalidating
        # any row number that's higher than the currently removed one.
        selection_list.sort(key=lambda selection: selection.row(), reverse=True)
        for selection in selection_list:
            model.removeRow(selection.row())

        # Model retains blank rows until we select() again.
        self.modeldb.racer_table_model.select()

    def update_field_name(self):
        """Update the window title.

        Update the window title with the field name corresponding to the field_id which we are
        using to filter our racer table view. If this is the general racer table view (not a field-
        specific one), then there's really not much to be done...the window title will always
        be the same.
        """
        if self.field_id:
            field_name = self.modeldb.field_table_model.name_from_id(self.field_id)
            self.setWindowTitle('Racers (%s)' % field_name)
            regexp = '^' + QRegExp.escape(field_name) + '$'
            self.proxy_model_filter.setFilterRegExp(QRegExp(regexp, Qt.CaseSensitive))
        else:
            self.setWindowTitle('Racers')

    def set_remote(self, remote):
        """Do everything needed for a remote that has just been connected."""
        self.remote = remote

        if self.remote:
            self.showColumn(self.source_model.status_column)
        else:
            self.hideColumn(self.source_model.status_column)

    def set_wall_times(self, wall_times):
        """Set whether to display wall times or time from reference clock."""
        self.proxy_model_msecs.set_wall_times(wall_times)

    def connect_preferences(self, preferences):
        """Connect preferences signals to the various slots that care."""
        if not preferences:
            return

        self.set_wall_times(preferences.wall_times_checkbox.isChecked())
        preferences.wall_times_checkbox.stateChanged.connect(self.proxy_model_msecs.set_wall_times)

    def read_settings(self):
        """Read settings."""
        group_name = self.__class__.__name__
        if self.field_id:
            field_name = self.modeldb.field_table_model.name_from_id(self.field_id)
            group_name = '_'.join([group_name, field_name])
        settings = QSettings()
        settings.beginGroup(group_name)

        self.resize(settings.value('size', defaults.RACER_TABLE_VIEW_SIZE))
        if settings.contains('pos'):
            self.move(settings.value('pos'))

        if settings.contains('horizontal_header_state'):
            self.horizontalHeader().restoreState(settings.value('horizontal_header_state'))

        settings.endGroup()

    def write_settings(self):
        """Write settings."""
        group_name = self.__class__.__name__
        if self.field_id:
            field_name = self.modeldb.field_table_model.name_from_id(self.field_id)
            group_name = '_'.join([group_name, field_name])
        settings = QSettings()
        settings.beginGroup(group_name)

        settings.setValue('size', self.size())
        settings.setValue('pos', self.pos())
        settings.setValue('horizontal_header_state', self.horizontalHeader().saveState())

        settings.endGroup()

    # Signals.
    visibleChanged = pyqtSignal(bool)

class ResultTableView(QTableView):
    """Table view for the result table model."""

    RESULT_TABLE_POINT_SIZE = 20

    def __init__(self, modeldb, parent=None):
        """Initialize the ResultTableView instance."""
        super().__init__(parent=parent)

        self.journal = Journal(modeldb.journal_table_model, 'results')

        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.modeldb = modeldb

        self.source_model = self.modeldb.result_table_model
        self.proxy_model = MSecsColumnsProxyModel(self.modeldb, parent=parent)
        self.proxy_model.setMSecsFromReferenceColumns([self.source_model.finish_column])
        self.proxy_model.setSourceModel(self.source_model)
        self.setModel(self.proxy_model)

        self.setAlternatingRowColors(True)
        self.setSortingEnabled(False) # Don't allow sorting.
        self.setSelectionBehavior(QTableView.SelectRows)
        self.sortByColumn(self.source_model.finish_column, Qt.AscendingOrder)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionsMovable(True)
        self.verticalHeader().setVisible(False)
        self.hideColumn(self.source_model.id_column)

        self.setup_tooltip()

        font = self.font()
        font.setPointSize(self.RESULT_TABLE_POINT_SIZE)
        self.setFont(font)

        self.read_settings()

    def keyPressEvent(self, event): #pylint: disable=invalid-name
        """Handle key presses."""
        if event.key() == Qt.Key_Backspace or event.key() == Qt.Key_Delete:
            self.handle_delete()

        return super().keyPressEvent(event)

    def hideEvent(self, event): #pylint: disable=invalid-name
        """Handle hide event."""
        del event
        self.write_settings()
        self.visibleChanged.emit(False)

    def eventFilter(self, watched, event): #pylint: disable=invalid-name
        """Event filter for showing/hiding a tool tip."""
        if self.viewport() == watched:
            if event.type() == QEvent.MouseMove:
                index = self.indexAt(event.pos())
                if index.isValid():
                    result_scratchpad_column = self.source_model.scratchpad_column
                    column = self.horizontalHeader().logicalIndex(result_scratchpad_column)
                    self.show_popup(index.siblingAtColumn(column))
                else:
                    self.popup.hide()
            elif event.type() == QEvent.Leave:
                self.popup.hide()
        elif self.popup == watched:
            if event.type() == QEvent.Leave:
                self.popup.hide()

        return super().eventFilter(watched, event)

    def mouseReleaseEvent(self, event): #pylint: disable=invalid-name
        """Do normal processing of mouse release, emit signal if this results in no selection.

        Emit clicked_without_selection signal if the mouse release (perhaps as a result of a click
        or double click) results in no selection. Useful for allowing this widget to be robbed of
        its keyboard focus.
        """
        super().mouseReleaseEvent(event)

        # See if there is a selection. If not, give up the keyboard focus.
        if not self.selectionModel().hasSelection():
            self.clicked_without_selection.emit()

    def setup_tooltip(self):
        """Set up the state required for supporting the racer info on hover tool tip."""
        self.popup = QDialog(self, Qt.Popup | Qt.ToolTip)

        layout = QVBoxLayout()
        self.popup_label = QLabel(self.popup)
        self.popup_label.setWordWrap(True)
        layout.addWidget(self.popup_label)
        self.popup.setLayout(layout)
        self.popup.installEventFilter(self)

        self.viewport().installEventFilter(self)
        self.setMouseTracking(True)

    def show_popup(self, index):
        """Show the racer info tool tip.

        The contents of the tool tip are gotten from trying to look up the racer at the index.
        If the scratch pad contents are not a proper bib number, then this won't work; display
        an appropriate message in the tool tip.
        """
        result_scratchpad_column = self.source_model.scratchpad_column
        bib = index.siblingAtColumn(result_scratchpad_column).data(Qt.DisplayRole)

        if not bib.isdigit():
            text = 'Invalid bib number'
        else:
            racer_table_model = self.modeldb.racer_table_model
            racer_bib_column = racer_table_model.bib_column
            racer_index_list = racer_table_model.match(racer_table_model.index(0, racer_bib_column),
                                                       Qt.DisplayRole, bib, 1, Qt.MatchExactly)
            if not racer_index_list:
                text = 'Unknown bib number'
            else:
                racer_index = racer_index_list[0]
                racer_first_name_column = racer_table_model.first_name_column
                racer_first_name_index = racer_index.siblingAtColumn(racer_first_name_column)
                racer_first_name = racer_first_name_index.data(Qt.DisplayRole)
                racer_last_name_column = racer_table_model.last_name_column
                racer_last_name_index = racer_index.siblingAtColumn(racer_last_name_column)
                racer_last_name = racer_last_name_index.data(Qt.DisplayRole)
                racer_team_column = racer_table_model.team_column
                racer_team_index = racer_index.siblingAtColumn(racer_team_column)
                racer_team = racer_team_index.data(Qt.DisplayRole)

                text = ' '.join([racer_first_name, racer_last_name])
                if racer_team:
                    text = (os.linesep+os.linesep).join([text, racer_team])

        rect = self.visualRect(index)
        self.popup.move(self.viewport().mapToGlobal(rect.bottomLeft()))
        self.popup_label.setText(text)
        self.popup.adjustSize()
        self.popup.show()

    def handle_delete(self):
        """Handle delete key press.

        On delete key press, delete the selection.
        """
        race_table_model = self.modeldb.race_table_model

        item_selection = self.selectionModel().selection()
        selection_list = self.selectionModel().selectedRows()

        # Remove rows from large to small, because the rows are removed
        # immediately, and cause the rest of the rows to shift, invalidating
        # any row number that's higher than the currently removed one.
        selection_list.sort(key=lambda selection: selection.row(), reverse=True)
        for selection in selection_list:
            record = self.source_model.record(selection.row())

            reference_datetime = race_table_model.get_reference_clock_datetime()
            bib = record.value(ResultTableModel.SCRATCHPAD)
            msecs = record.value(ResultTableModel.FINISH)
            finish = reference_datetime.addMSecs(msecs).toString(defaults.DATETIME_FORMAT)

            self.journal.log('Result with bib "%s" and time "%s" deleted.' % (bib, finish))

            self.source_model.removeRow(selection.row())

        # Model retains blank rows until we select() again.
        self.modeldb.result_table_model.select()

        # Selection changed because of this deletion, but for some reason,
        # this widget class doesn't emit the selectionChanged signal in this
        # case. Let's emit it ourselves.
        #
        # Not gonna bother calculating selected and deselected. Hopefully,
        # slots that receive this signal won't care...
        self.selectionModel().selectionChanged.emit(QItemSelection(), item_selection)

        # Emit resultDeleted signal.
        self.resultDeleted.emit()

    # Signals.
    resultDeleted = pyqtSignal()

    def handle_submit(self):
        """Handle submit button click.

        On submit button click, we try to push the finish times for the selected rows to the
        corresponding racer. For each selection that succeeds, we remove that row from this table.
        """
        race_table_model = self.modeldb.race_table_model

        selection_list = self.selectionModel().selectedRows()

        # Remove rows from large to small, because the rows are removed
        # immediately, and cause the rest of the rows to shift, invalidating
        # any row number that's higher than the currently removed one.
        selection_list.sort(key=lambda selection: selection.row(), reverse=True)
        deleted_selection = QItemSelection()
        for selection in selection_list:
            try:
                # Only try to submit it if it's a non-negative integer.
                # Else, it is obviously a work in progress, so don't even
                # bother.
                record = self.source_model.record(selection.row())
                scratchpad = record.value(ResultTableModel.SCRATCHPAD)
                if scratchpad.isdigit():
                    self.source_model.submit_result(selection.row())
                    deleted_selection.select(selection, selection)

                    reference_datetime = race_table_model.get_reference_clock_datetime()
                    bib = record.value(ResultTableModel.SCRATCHPAD)
                    msecs = record.value(ResultTableModel.FINISH)
                    finish = reference_datetime.addMSecs(msecs).toString(defaults.DATETIME_FORMAT)

                    self.journal.log('Result with bib "%s" and time "%s" submitted.' %
                                     (bib, finish))

            except InputError as e:
                QMessageBox.warning(self, 'Error', str(e))

        # Model retains blank rows until we select() again.
        self.source_model.select()

        # Surprisingly, when the model changes such that our selection changes
        # (for example, when the selected result gets submitted to the racer
        # table model and gets deleted from the result table model), the
        # selectionChanged signal is NOT emitted. So, we have to emit that
        # ourselves here.
        self.selectionModel().selectionChanged.emit(QItemSelection(), deleted_selection)

    def set_wall_times(self, wall_times):
        """Set whether to display wall times or time from reference clock."""
        self.proxy_model.wall_times = wall_times

    def connect_preferences(self, preferences):
        """Connect preferences signals to the various slots that care."""
        if not preferences:
            return

        self.set_wall_times(preferences.wall_times_checkbox.isChecked())
        preferences.wall_times_checkbox.stateChanged.connect(self.proxy_model.set_wall_times)

    def read_settings(self):
        """Read settings."""
        group_name = self.__class__.__name__
        settings = QSettings()
        settings.beginGroup(group_name)

        self.resize(settings.value('size', defaults.RESULT_TABLE_VIEW_SIZE))
        if settings.contains('pos'):
            self.move(settings.value('pos'))

        if settings.contains('horizontal_header_state'):
            self.horizontalHeader().restoreState(settings.value('horizontal_header_state'))

        settings.endGroup()

    def write_settings(self):
        """Write settings."""
        group_name = self.__class__.__name__
        settings = QSettings()
        settings.beginGroup(group_name)

        settings.setValue('size', self.size())
        settings.setValue('pos', self.pos())
        settings.setValue('horizontal_header_state', self.horizontalHeader().saveState())

        settings.endGroup()

    # Signals.
    visibleChanged = pyqtSignal(bool)
    clicked_without_selection = pyqtSignal()
