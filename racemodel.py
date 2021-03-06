#!/usr/bin/env python3

"""RaceModel Qt Classes

This module contains the model-side of the model-view pattern. In particular, it is a wrapper
around the database tables that contain all of the race data, including fields, racers, and
miscellaneous persisted race information. This module also hides the details of the database
transactions. Users of this module will interact with the tables via Qt's QSqlTableModel and
related classes.

Users of this module should instantiate ModelDatabase, which is the top-level class, and contains
the various table models. It does not make sense to instantiate the table models separately,
since those table models presuppose the existence of the ModelDatabase instance. In fact, the
various table classes don't operate independently from one another...there are interdependencies,
and they get to sibling tables via the ModelDatabase instance.
"""

import os
import sys
from PyQt5.QtCore import QDate, QDateTime, QModelIndex, QObject, Qt, QTime
from PyQt5.QtGui import QBrush, QTextDocument
from PyQt5.QtSql  import QSqlDatabase, QSqlQuery, QSqlRelation, QSqlRelationalTableModel, \
                         QSqlTableModel
from PyQt5.QtWidgets import QPlainTextDocumentLayout
import common
import defaults

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

EMPTY_JSON = '{}'

# I know there's no max int value in python3, but since we're storing msecs time deltas as INT types
# in the database, the database is probably using 64-bit signed integers. We need a few values with
# special meanings, so use a few super-negative numbers for this purpose since it is unlikely that
# these will end up being legitimate msecs time delta values.
#
# Also, reserve a whole bunch just in case we need more.
MSECS_UNINITIALIZED = -sys.maxsize
MSECS_DNS = -sys.maxsize + 1
MSECS_DNF = -sys.maxsize + 2
MSECS_DNP = -sys.maxsize + 3
MSECS_SMALLEST_VALID = -sys.maxsize + 100

def msecs_is_valid(msecs):
    """Returns whether msecs holds a valid (non-negative) elapsed time."""
    return msecs > MSECS_SMALLEST_VALID

def msecs_to_string(msecs):
    """Return a string representation of time delta expressed as msecs."""
    if msecs_is_valid(msecs):
        days = msecs // (24 * 60 * 60 * 1000)
        hours = (msecs - days) // (60 * 60 * 1000)

        if days and hours:
            string = QTime(0, 0).addMSecs(msecs).toString('%s days, h:mm:ss.zzz' % days)
        elif days:
            string = QTime(0, 0).addMSecs(msecs).toString('%s days, m:ss.zzz' % days)
        elif hours:
            string = QTime(0, 0).addMSecs(msecs).toString('h:mm:ss.zzz')
        else:
            string = QTime(0, 0).addMSecs(msecs).toString('m:ss.zzz')
    elif msecs in (MSECS_DNF, MSECS_UNINITIALIZED):
        string = 'DNF'
    elif msecs == MSECS_DNP:
        string = 'DNP'
    elif msecs == MSECS_DNS:
        string = 'DNS'
    else:
        string = 'unknown'

    return string

class DatabaseError(Exception):
    """Database Error exception

    This exception is thrown when Qt's database stuff encounters an error. Qt likes to have their
    functions/methods return True or False to denote return status, and this is basically an
    exception wrapper around that.
    """

class InputError(Exception):
    """Input Error exception

    This exception is thrown when some input argument to a method doesn't look right. It almost
    certainly is a result of user input error, so the proper response is to put up a QMessageBox
    telling the user that they did something wrong.
    """

def _print_record(record):
    """Print a Qt SQL record.

    This is used for debugging.
    """
    for index in range(record.count()):
        print('%s: %s, generated = %s' % (record.field(index).name(),
                                          record.field(index).value(),
                                          record.isGenerated(index)))

class ModelDatabase(QObject):
    """Model Database

    This is the top-level class that encapsulates all of the database tables.
    """

    def __init__(self, filename, new=False):
        """Initialize the ModelDatabase instance."""
        super().__init__()

        self.filename = filename

        if new:
            # Delete the file, if it exists.
            if os.path.exists(self.filename):
                os.remove(self.filename)

        self.db = QSqlDatabase.addDatabase('QSQLITE', self.filename)

        if not self.db.isValid():
            raise DatabaseError('Invalid database')

        self.db.setDatabaseName(filename)

        if not self.db.open():
            raise DatabaseError(self.db.lastError().text())

        # Make sure we make the journal table first, so we can immediately
        # start to use it.
        self.journal_table_model = JournalTableModel(self)
        self.race_table_model = RaceTableModel(self)
        self.field_table_model = FieldTableModel(self)
        self.racer_table_model = RacerTableModel(self)
        self.result_table_model = ResultTableModel(self)

    def cleanup(self):
        """Close the database."""
        self.db.close()
        QSqlDatabase.removeDatabase(self.filename)

    def add_defaults(self):
        """Add default table entries."""
        self.journal_table_model.add_defaults()
        self.race_table_model.add_defaults()
        self.field_table_model.add_defaults()
        self.racer_table_model.add_defaults()
        self.result_table_model.add_defaults()

class Journal(QObject):
    """Journal helper class.

    This class is meant to simplify the use of the journal database table.
    With this class, you don't have to keep referring to the journal table
    model...just pass it in once when we make an instance of this class. We
    can also give it a topic (or not).

    After making one of these, simply do:
    journal.log(message)

    """
    def __init__(self, journal_table_model, topic):
        """Initialize the Journal instance."""
        super().__init__()

        self.journal_table_model = journal_table_model
        self.topic = topic

    def log(self, message):
        """Log a journal entry."""
        self.journal_table_model.add_entry(self.topic, message)

class TableModel(QSqlRelationalTableModel):
    """Table Model base class

    This is the parent class of the database table classes. Basically, it commonizes the management
    of column flags. I'm not sure why the Qt SQL table model classes don't have these already.
    """

    def __init__(self, modeldb):
        """Initialize the TableModel instance."""
        super().__init__(db=modeldb.db)

        self.modeldb = modeldb
        self.column_flags_to_add = {}
        self.column_flags_to_remove = {}

    def create_table(self):
        """Create the database table."""
        raise NotImplementedError

    def add_defaults(self):
        """Add default table entries."""

    def add_column_flags(self, column, flags):
        """Add flags to specified column.

        This is used by the flags() method to modify the column flags that are returned.
        """
        if not column in self.column_flags_to_add.keys():
            self.column_flags_to_add[column] = 0
        self.column_flags_to_add[column] |= int(flags)

    def remove_column_flags(self, column, flags):
        """Remove flags from specified column.

        This is used by the flags() method to modify the column flags that are returned.
        """
        if not column in self.column_flags_to_remove.keys():
            self.column_flags_to_remove[column] = 0
        self.column_flags_to_remove[column] |= int(flags)

    def flags(self, model_index):
        """Override parent QSqlRelationalTableModel to modify the column flags returned."""
        flags = super().flags(model_index)

        column = model_index.column()

        if not column in self.column_flags_to_add.keys():
            self.column_flags_to_add[column] = 0
        flags |= self.column_flags_to_add[column]

        if not column in self.column_flags_to_remove.keys():
            self.column_flags_to_remove[column] = 0
        flags &= ~self.column_flags_to_remove[model_index.column()]

        return flags

    def insertRecord(self, row, record): #pylint: disable=invalid-name
        """Redefine this so we can raise an exception.

        The parent's version of this method returns True on success, False on error. Re-implement
        this to raise a DatabaseError.
        """
        if not super().insertRecord(row, record):
            raise DatabaseError(self.lastError().text())

        return True

    def removeRow(self, row): #pylint: disable=invalid-name
        """Redefine this so we can raise an exception.

        The parent's version of this method returns True on success, False on error. Re-implement
        this to raise a DatabaseError.
        """
        if not super().removeRow(row):
            raise DatabaseError(self.lastError().text())

        return True

    def select(self):
        """Redefine this so we can raise an exception.

        The parent's version of this method returns True on success, False on error. Re-implement
        this to raise a DatabaseError.
        """
        if not super().select():
            raise DatabaseError(self.lastError().text())

        return True

    def submitAll(self): #pylint: disable=invalid-name
        """Redefine this so we can raise an exception.

        The parent's version of this method returns True on success, False on error. Re-implement
        this to raise a DatabaseError.
        """
        if not super().submitAll():
            raise DatabaseError(self.lastError().text())

        return True

    @staticmethod
    def area_contains(top_left, bottom_right, column, row=None):
        """Determine if the area contains the column (and optionally the row).

        Does the area described by model indexes top_left and bottom_right contain the column
        (and the row, if specified)?
        """
        if top_left.column() > column or bottom_right.column() < column:
            return False

        if row and (top_left.row() > row or bottom_right.row() < row):
            return False

        return True

class JournalTableModel(TableModel):
    """Journal Table Model

    This table contains an activity journal (model transactions, etc). Since we are too lazy to
    implement proper undo support, this journal can be used to manually correct mistakes in the
    race scoring process. Views of this model should hopefully provide sufficiently rich sorting
    and filtering to make this useful.

    TOPIC is meant to be a general facility code, for coarse filtering. For example, "racer".
    MESSAGE is the long, detailed message.
    """

    TABLE = 'journal'
    ID = 'id'
    TIMESTAMP = 'timestamp'
    TOPIC = 'topic'
    MESSAGE = 'message'

    def __init__(self, modeldb):
        """Initialize the ResultTableModel instance."""
        super().__init__(modeldb)

        self.create_table()

        self.setEditStrategy(QSqlTableModel.OnFieldChange)
        self.setTable(self.TABLE)

        # We need the field index so often, just save them here since they never change.
        self.id_column = self.fieldIndex(self.ID)
        self.timestamp_column = self.fieldIndex(self.TIMESTAMP)
        self.topic_column = self.fieldIndex(self.TOPIC)
        self.message_column = self.fieldIndex(self.MESSAGE)

        self.setHeaderData(self.timestamp_column, Qt.Horizontal, 'Timestamp')
        self.setHeaderData(self.topic_column, Qt.Horizontal, 'Topic')
        self.setHeaderData(self.message_column, Qt.Horizontal, 'Message')

        self.select()

    def create_table(self):
        """Create the database table."""
        query = QSqlQuery(self.database())

        if not query.exec(
            'CREATE TABLE IF NOT EXISTS "%s" ' % self.TABLE +
            '("%s" INTEGER NOT NULL PRIMARY KEY, ' % self.ID +
             '"%s" DATETIME NOT NULL, ' % self.TIMESTAMP +
             '"%s" TEXT NOT NULL, ' % self.TOPIC +
             '"%s" TEXT NOT NULL);' % self.MESSAGE):
            raise DatabaseError(query.lastError().text())

        query.finish()

    def add_entry(self, topic=None, message=None):
        """Add a row to the database table."""
        # Generate our time stamp here...no need for the caller to make one.
        timestamp = QDateTime.currentDateTime()

        record = self.record()
        record.setGenerated(self.ID, False)
        record.setValue(self.TIMESTAMP, timestamp)
        record.setValue(self.TOPIC, topic)
        record.setValue(self.MESSAGE, message)

        self.insertRecord(-1, record)

class RaceTableModel(TableModel):
    """Race Table Model

    This table contains key-value pairs that serve as properties of the race. Essentially a
    dictionary, these can be used for miscellaneous information. Currently, it holds stuff like
    race name, race date, race notes, and remote-specific stuff.
    """

    TABLE = 'race'
    ID = 'id'
    KEY = 'key'
    VALUE = 'value'

    # Race keys
    NAME = 'name'
    DATE = 'date'
    NOTES = 'notes'
    REFERENCE_CLOCK_ENABLED = 'reference_clock_enabled'
    REFERENCE_CLOCK_DATETIME = 'reference_clock_datetime'
    REMOTE_CLASS = 'remote_class'

    def __init__(self, modeldb):
        """Initialize the RaceTableModel instance."""
        super().__init__(modeldb)

        self.create_table()

        self.setEditStrategy(QSqlTableModel.OnFieldChange)
        self.setTable(self.TABLE)

        # We need the field index so often, just save them here since they never change.
        self.id_column = self.fieldIndex(self.ID)
        self.key_column = self.fieldIndex(self.KEY)
        self.value_column = self.fieldIndex(self.VALUE)

        self.select()

    def create_table(self):
        """Create the database table."""
        query = QSqlQuery(self.database())

        if not query.exec(
            'CREATE TABLE IF NOT EXISTS "%s" ' % self.TABLE +
            '("%s" INTEGER NOT NULL PRIMARY KEY, ' % self.ID +
             '"%s" TEXT NOT NULL, ' % self.KEY +
             '"%s" TEXT NOT NULL);' % self.VALUE):
            raise DatabaseError(query.lastError().text())

        query.finish()

    def add_defaults(self):
        """Add default table entries."""
        if not self.get_race_property(self.NAME):
            self.set_race_property(self.NAME, defaults.RACE_NAME)

        if not self.get_race_property(self.DATE):
            self.set_date(QDateTime.currentDateTime().date())

        if not self.get_race_property(self.NOTES):
            document = QTextDocument()
            document.setDocumentLayout(QPlainTextDocumentLayout(document))
            self.set_notes(document)

    def get_race_property(self, key):
        """Get the value of the race property corresponding to the "key"."""
        index_list = self.match(self.index(0, self.key_column),
                                Qt.DisplayRole, key, 1, Qt.MatchExactly)

        if not index_list:
            return None

        index = index_list[0]

        return self.data(self.index(index.row(), self.value_column))

    def set_race_property(self, key, value=''):
        """Set/add a value corresponding to "key".

        Set the row corresponding to the given "key" to "value". If this row doesn't exist, add a
        new row.
        """
        index_list = self.match(self.index(0, self.key_column),
                                Qt.DisplayRole, key, 1, Qt.MatchExactly)

        if not index_list:
            record = self.record()
            record.setGenerated(self.ID, False)
            record.setValue(self.KEY, key)
            record.setValue(self.VALUE, value)

            self.insertRecord(-1, record)
            return

        index = index_list[0]
        self.setData(index.siblingAtColumn(self.value_column), value)

    def delete_race_property(self, key):
        """Delete a key/value entry from the database."""
        index_list = self.match(self.index(0, self.key_column),
                                Qt.DisplayRole, key, 1, Qt.MatchExactly)

        if not index_list:
            return

        index = index_list[0]

        self.removeRow(index.row())

    def get_date(self):
        """Get the date, as a QDate."""
        return QDate.fromString(self.get_race_property(self.DATE), Qt.ISODate)

    def set_date(self, date):
        """Set the date, as a QDate."""
        self.set_race_property(self.DATE, date.toString(Qt.ISODate))

    def get_notes(self):
        """Get the notes, as a QTextDocument."""
        document = QTextDocument(self.get_race_property(self.NOTES))
        document.setDocumentLayout(QPlainTextDocumentLayout(document))
        return document

    def set_notes(self, notes):
        """Set the notes, as a QTextDocument."""
        self.set_race_property(self.NOTES, notes.toPlainText())

    def enable_reference_clock(self):
        """Enable reference clock."""
        self.set_race_property(self.REFERENCE_CLOCK_ENABLED)

    def disable_reference_clock(self):
        """Disable reference clock.

        Note that we only disable the previously set-up reference datetime (by deleting the
        "enabled" property), but we keep the actual reference datetime around in case we want to
        come back to it.
        """
        self.delete_race_property(self.REFERENCE_CLOCK_ENABLED)

    def reference_clock_is_enabled(self):
        """Return whether the reference clock is enabled."""
        return not self.get_race_property(self.REFERENCE_CLOCK_ENABLED) is None

    def get_reference_clock_datetime(self):
        """Get reference datetime.

        If there is no reference time, use midnight (time zero) of the current day.
        """
        wall_clock_datetime = QDateTime(QDate.currentDate())

        if not self.reference_clock_is_enabled():
            return wall_clock_datetime

        datetime_string = self.get_race_property(self.REFERENCE_CLOCK_DATETIME)
        if not datetime_string:
            return wall_clock_datetime

        reference_datetime = QDateTime.fromString(datetime_string, Qt.ISODateWithMs)
        if not reference_datetime.isValid():
            return wall_clock_datetime

        return reference_datetime

    def set_reference_clock_datetime(self, reference_datetime):
        """Set reference datetime.

        reference_datetime should be a QDateTime instance.
        """
        datetime_string = reference_datetime.toString(Qt.ISODateWithMs)
        self.set_race_property(self.REFERENCE_CLOCK_DATETIME, datetime_string)

    def reference_clock_has_datetime(self):
        """Return whether there is a reference datetime set up."""
        return not self.get_race_property(self.REFERENCE_CLOCK_DATETIME) is None

    def get_reference_msecs(self):
        """Get number of milliseconds elapsed since reference time zero."""
        reference_datetime = self.get_reference_clock_datetime()
        current_datetime = QDateTime.currentDateTime()

        return reference_datetime.msecsTo(current_datetime)

    def get_wall_time_msecs(self):
        """Get the number of milliseconds elapsed since today at midnight."""
        reference_datetime = QDateTime(QDate.currentDate())
        current_datetime = QDateTime.currentDateTime()

        return reference_datetime.msecsTo(current_datetime)

    def change_reference_clock_datetime(self, old_datetime, new_datetime):
        """Undo old reference clock datetime, and apply new reference clock datetime."""
        # Nothing to do.
        if old_datetime == new_datetime:
            return

        self.modeldb.racer_table_model.change_reference_clock_datetime(old_datetime, new_datetime)

class FieldTableModel(TableModel):
    """Field Table Model

    This table contains the race fields.
    """

    TABLE = 'field'
    ID = 'id'
    NAME = 'name'
    SUBFIELDS = 'subfields'
    METADATA = 'metadata'

    def __init__(self, modeldb):
        """Initialize the FieldTableModel instance."""
        super().__init__(modeldb)

        self.create_table()

        self.setEditStrategy(QSqlTableModel.OnFieldChange)
        self.setTable(self.TABLE)

        # We need the field index so often, just save them here since they never change.
        self.id_column = self.fieldIndex(self.ID)
        self.name_column = self.fieldIndex(self.NAME)
        self.subfields_column = self.fieldIndex(self.SUBFIELDS)
        self.metadata_column = self.fieldIndex(self.METADATA)

        self.setHeaderData(self.name_column, Qt.Horizontal, 'Field')
        self.setHeaderData(self.subfields_column, Qt.Horizontal, 'Subfields')
        self.setHeaderData(self.metadata_column, Qt.Horizontal, 'Metadata')

        self.select()

    def create_table(self):
        """Create the database table."""
        query = QSqlQuery(self.database())

        if not query.exec(
            'CREATE TABLE IF NOT EXISTS "%s" ' % self.TABLE +
            '("%s" INTEGER NOT NULL PRIMARY KEY, ' % self.ID +
             '"%s" TEXT UNIQUE NOT NULL, ' % self.NAME +
             '"%s" TEXT NOT NULL, ' % self.SUBFIELDS +
             '"%s" TEXT NOT NULL);' % self.METADATA):
            raise DatabaseError(query.lastError().text())

        query.finish()

    def add_defaults(self):
        """Add default table entries."""
        if self.rowCount() == 0:
            self.add_field(defaults.FIELD_NAME)

    def name_from_id(self, field_id):
        """Get field name, from field ID."""
        index_list = self.match(self.index(0, self.id_column),
                                Qt.DisplayRole, field_id, 1, Qt.MatchExactly)

        if not index_list:
            return None

        index = index_list[0]

        return self.data(self.index(index.row(), self.name_column))

    def id_from_name(self, name):
        """Get field ID, from field name."""
        index_list = self.match(self.index(0, self.name_column),
                                Qt.DisplayRole, name, 1, Qt.MatchExactly)

        if not index_list:
            return None

        index = index_list[0]

        return self.data(self.index(index.row(), self.id_column))

    def add_field(self, name, subfields='', metadata=EMPTY_JSON):
        """Add a row to the database table."""
        if name == '':
            raise InputError('Field name "%s" is invalid' % name)

        dup_field_index = self.match(self.index(0, self.name_column),
                                     Qt.DisplayRole, name, 1, Qt.MatchExactly)
        if dup_field_index:
            raise InputError('Field name "%s" is already being used.' % name)

        record = self.record()
        record.setGenerated(self.ID, False)
        record.setValue(self.NAME, name)
        record.setValue(self.SUBFIELDS, subfields)
        record.setValue(self.METADATA, metadata)

        self.insertRecord(-1, record)

    def delete_field(self, name):
        """Delete a row from the database table."""
        index_list = self.match(self.index(0, self.name_column),
                                Qt.DisplayRole, name, 1, Qt.MatchExactly)

        if not index_list:
            raise InputError('Failed to find field with name %s' % name)

        index = index_list[0]

        self.removeRow(index.row())

    def get_field_metadata(self, name):
        """Returns the metadata of the field identified by "name"."""
        index_list = self.match(self.index(0, self.name_column),
                                Qt.DisplayRole, name, 1, Qt.MatchExactly)

        if not index_list:
            raise InputError('Failed to find field with name %s' % name)

        record = self.record(index_list[0].row())
        return record.value(self.METADATA)

    def set_field_metadata(self, name, metadata):
        """Sets the metadata of the field identified by "name"."""
        index_list = self.match(self.index(0, self.name_column),
                                Qt.DisplayRole, name, 1, Qt.MatchExactly)

        if not index_list:
            raise InputError('Failed to find field with name %s' % name)

        index = index_list[0].siblingAtColumn(self.metadata_column)
        self.setData(index, metadata)
        self.dataChanged.emit(index, index)

    def get_subfields(self, name):
        """Get the value of the subfields column of the row specified by the field name.

        This subfield is used for generating reports for fields that race together but are picked
        separately.
        """
        index_list = self.match(self.index(0, self.name_column),
                                Qt.DisplayRole, name, 1, Qt.MatchExactly)

        if not index_list:
            return None

        index = index_list[0]

        return self.data(self.index(index.row(), self.subfields_column))

    def data(self, index, role=Qt.DisplayRole):
        """Color-code the row according to whether no, some, or all racers have finished."""
        if role == Qt.BackgroundRole:
            racer_table_model = self.modeldb.racer_table_model

            field_name = self.record(index.row()).value(self.NAME)

            total = racer_table_model.racer_count_total_in_field(field_name)
            finished = racer_table_model.racer_count_finished_in_field(field_name)

            if total != 0:
                if finished == total:
                    return QBrush(Qt.green)
                elif finished > 0:
                    return QBrush(Qt.yellow)

        return super().data(index, role)

class RacerTableModel(TableModel):
    """Racer Table Model

    This table contains the racers.
    """

    TABLE = 'racer'
    ID = 'id'
    BIB = 'bib'
    FIRST_NAME = 'first_name'
    LAST_NAME = 'last_name'
    FIELD = 'field_id'
    FIELD_ALIAS = 'name'
    CATEGORY = 'category'
    TEAM = 'team'
    AGE = 'age'
    START = 'start'
    FINISH = 'finish'
    STATUS = 'status'
    METADATA = 'metadata'

    def __init__(self, modeldb):
        """Initialize the RacerTableModel instance."""
        super().__init__(modeldb)

        self.remote = None

        self.create_table()

        self.setEditStrategy(QSqlTableModel.OnFieldChange)
        self.setTable(self.TABLE)

        # We need the field index so often, just save them here since they never change.
        self.id_column = self.fieldIndex(self.ID)
        self.bib_column = self.fieldIndex(self.BIB)
        self.first_name_column = self.fieldIndex(self.FIRST_NAME)
        self.last_name_column = self.fieldIndex(self.LAST_NAME)
        self.field_column = self.fieldIndex(self.FIELD)
        self.category_column = self.fieldIndex(self.CATEGORY)
        self.team_column = self.fieldIndex(self.TEAM)
        self.age_column = self.fieldIndex(self.AGE)
        self.start_column = self.fieldIndex(self.START)
        self.finish_column = self.fieldIndex(self.FINISH)
        self.status_column = self.fieldIndex(self.STATUS)
        self.metadata_column = self.fieldIndex(self.METADATA)

        self.setHeaderData(self.bib_column, Qt.Horizontal, 'Bib')
        self.setHeaderData(self.first_name_column, Qt.Horizontal, 'First Name')
        self.setHeaderData(self.last_name_column, Qt.Horizontal, 'Last Name')
        self.setHeaderData(self.field_column, Qt.Horizontal, 'Field')
        self.setHeaderData(self.category_column, Qt.Horizontal, 'Cat')
        self.setHeaderData(self.team_column, Qt.Horizontal, 'Team')
        self.setHeaderData(self.age_column, Qt.Horizontal, 'Age')
        self.setHeaderData(self.start_column, Qt.Horizontal, 'Start')
        self.setHeaderData(self.finish_column, Qt.Horizontal, 'Finish')
        self.setHeaderData(self.status_column, Qt.Horizontal, 'Status')
        self.setHeaderData(self.metadata_column, Qt.Horizontal, 'Metadata')

        # After this relation is defined, the field name becomes
        # "field_name_2" (FIELD_ALIAS).
        self.setRelation(self.field_column, QSqlRelation(FieldTableModel.TABLE,
                                                         FieldTableModel.ID,
                                                         FieldTableModel.NAME))

        self.select()

    def create_table(self):
        """Create the database table."""
        query = QSqlQuery(self.database())

        if not query.exec(
            'CREATE TABLE IF NOT EXISTS "%s" ' % self.TABLE +
            '("%s" INTEGER NOT NULL PRIMARY KEY, ' % self.ID +
             '"%s" INTEGER UNIQUE NOT NULL, ' % self.BIB +
             '"%s" TEXT NOT NULL, ' % self.FIRST_NAME +
             '"%s" TEXT NOT NULL, ' % self.LAST_NAME +
             '"%s" INTEGER NOT NULL, ' % self.FIELD +
             '"%s" TEXT NOT NULL, ' % self.CATEGORY +
             '"%s" TEXT NOT NULL, ' % self.TEAM +
             '"%s" INTEGER NOT NULL, ' % self.AGE +
             '"%s" INTEGER NOT NULL, ' % self.START +
             '"%s" INTEGER NOT NULL, ' % self.FINISH +
             '"%s" TEXT NOT NULL, ' % self.STATUS +
             '"%s" TEXT NOT NULL);' % self.METADATA):
            raise DatabaseError(query.lastError().text())

        query.finish()

    def add_racer(self, bib, first_name, last_name, field, category, team, age,
                  start=MSECS_UNINITIALIZED, finish=MSECS_UNINITIALIZED, status='',
                  metadata=EMPTY_JSON):
        """Add a row to the database table.

        Do some validation.

        Don't have to check for None, because that would fail the NOT NULL table constraint.

        Also, default QDateTime constructor makes an invalid time that ends up being stored as NULL
        in the table, which is what we want.
        """
        dup_racer_index = self.match(self.index(0, self.bib_column),
                                     Qt.DisplayRole, bib, 1, Qt.MatchExactly)
        if dup_racer_index:
            dup_racer_first_name = dup_racer_index[0].siblingAtColumn(self.first_name_column).data()
            dup_racer_last_name = dup_racer_index[0].siblingAtColumn(self.last_name_column).data()

            dup_racer_name = ' '.join([dup_racer_first_name, dup_racer_last_name])

            raise InputError('Racer bib "%s" is already being used by %s.' %
                             (bib, dup_racer_name))

        if first_name == '' and last_name == '':
            raise InputError('Racer first and last name is .')

        # See if the field exists in our Field table.  If not, we add a new
        # field.
        if not field:
            raise InputError('Racer field is missing.' % field)

        field_id = self.modeldb.field_table_model.id_from_name(field)
        if not field_id:
            self.modeldb.field_table_model.add_field(field)
            field_id = self.modeldb.field_table_model.id_from_name(field)

        if field_id is None:
            raise InputError('Racer field "%s" is invalid.' % field)

        record = self.record()
        record.setGenerated(self.ID, False)
        record.setValue(self.BIB, bib)
        record.setValue(self.FIRST_NAME, first_name)
        record.setValue(self.LAST_NAME, last_name)

        # OMFG I can't believe I have to do this...but Qt is not re-translating
        # this stupid field_name_2 alias back to its original field name,
        # so the database ends up getting the alias instead of the proper
        # one, failing the transaction. This piece of code switches the
        # field back from the field_name_2 alias to the original field_id,
        # so that the ensuing SQL query can work.
        sql_field = record.field(self.field_column)
        sql_field.setName(self.FIELD)
        record.replace(self.field_column, sql_field)
        record.setValue(self.FIELD, field_id)

        record.setValue(self.CATEGORY, category)
        record.setValue(self.TEAM, team)
        record.setValue(self.AGE, age)
        record.setValue(self.START, start)
        record.setValue(self.FINISH, finish)
        record.setValue(self.STATUS, status)
        record.setValue(self.METADATA, metadata)

        self.insertRecord(-1, record)

    def update_racer(self, bib, first_name, last_name, field, category, team, age, #pylint: disable=too-many-branches
                     start=MSECS_UNINITIALIZED, finish=MSECS_UNINITIALIZED, status='',
                     metadata=EMPTY_JSON):
        """Update a row in the racer database table.

        Do some validation.

        Don't have to check for None, because that would fail the NOT NULL table constraint.

        Also, default QDateTime constructor makes an invalid time that ends up being stored as NULL
        in the table, which is what we want.
        """
        index_list = self.match(self.index(0, self.bib_column),
                                Qt.DisplayRole, bib, 1, Qt.MatchExactly)
        if not index_list:
            raise InputError('Racer bib %s not found.' % bib)

        if first_name == '' and last_name == '':
            raise InputError('Racer first and last name is .')

        # See if the field exists in our Field table.  If not, we add a new
        # field.
        if not field:
            raise InputError('Racer field is missing.' % field)

        field_id = self.modeldb.field_table_model.id_from_name(field)
        if not field_id:
            self.modeldb.field_table_model.add_field(field)
            field_id = self.modeldb.field_table_model.id_from_name(field)

        if field_id is None:
            raise InputError('Racer field "%s" is invalid.' % field)

        record = self.record(index_list[0].row())

        if record.value(self.FIRST_NAME) != first_name:
            index = index_list[0].siblingAtColumn(self.first_name_column)
            self.setData(index, first_name)
            self.dataChanged.emit(index, index)

        if record.value(self.LAST_NAME) != last_name:
            index = index_list[0].siblingAtColumn(self.last_name_column)
            self.setData(index, last_name)
            self.dataChanged.emit(index, index)

        if record.value(self.FIELD) != field_id:
            index = index_list[0].siblingAtColumn(self.field_column)
            self.setData(index, field_id)
            self.dataChanged.emit(index, index)

        if record.value(self.CATEGORY) != category:
            index = index_list[0].siblingAtColumn(self.category_column)
            self.setData(index, category)
            self.dataChanged.emit(index, index)

        if record.value(self.TEAM) != team:
            index = index_list[0].siblingAtColumn(self.team_column)
            self.setData(index, team)
            self.dataChanged.emit(index, index)

        if record.value(self.AGE) != age:
            index = index_list[0].siblingAtColumn(self.age_column)
            self.setData(index, age)
            self.dataChanged.emit(index, index)

        if record.value(self.START) != start:
            index = index_list[0].siblingAtColumn(self.start_column)
            self.setData(index, start)
            self.dataChanged.emit(index, index)

        if record.value(self.FINISH) != finish:
            index = index_list[0].siblingAtColumn(self.finish_column)
            self.setData(index, finish)
            self.dataChanged.emit(index, index)

        if record.value(self.STATUS) != status:
            index = index_list[0].siblingAtColumn(self.status_column)
            self.setData(index, status)
            self.dataChanged.emit(index, index)

        if record.value(self.METADATA) != metadata:
            index = index_list[0].siblingAtColumn(self.metadata_column)
            self.setData(index, metadata)
            self.dataChanged.emit(index, index)

    def delete_racer(self, bib):
        """Delete a row from the database table."""
        index_list = self.match(self.index(0, self.bib_column),
                                Qt.DisplayRole, bib, 1, Qt.MatchExactly)

        if not index_list:
            raise InputError('Failed to find racer with BIB %s' % bib)

        index = index_list[0]

        self.removeRow(index.row())

    def racer_exists(self, bib):
        """Returns True if racer exists, otherwise False."""
        index_list = self.match(self.index(0, self.bib_column),
                                Qt.DisplayRole, bib, 1, Qt.MatchExactly)

        return bool(index_list)

    def get_racer_metadata(self, bib):
        """Returns the metadata of the racer identified by "bib"."""
        index_list = self.match(self.index(0, self.bib_column),
                                Qt.DisplayRole, bib, 1, Qt.MatchExactly)

        if not index_list:
            raise InputError('Failed to find racer with bib %s' % bib)

        record = self.record(index_list[0].row())
        return record.value(self.METADATA)

    def set_racer_metadata(self, bib, metadata):
        """Returns the metadata of the racer identified by "bib"."""
        index_list = self.match(self.index(0, self.bib_column),
                                Qt.DisplayRole, bib, 1, Qt.MatchExactly)

        if not index_list:
            raise InputError('Failed to find racer with bib %s' % bib)

        index = index_list[0].siblingAtColumn(self.metadata_column)
        self.setData(index, metadata)
        self.dataChanged.emit(index, index)

    def set_racer_start(self, bib, start):
        """Set start time of the racer identified by "bib"."""
        index_list = self.match(self.index(0, self.bib_column),
                                Qt.DisplayRole, bib, 1, Qt.MatchExactly)

        if not index_list:
            raise InputError('Failed to find racer with bib %s' % bib)

        index = index_list[0].siblingAtColumn(self.start_column)
        self.setData(index, start)
        self.dataChanged.emit(index, index)

    def set_racer_finish(self, bib, finish):
        """Set finish time of the racer identified by "bib"."""
        index_list = self.match(self.index(0, self.bib_column),
                                Qt.DisplayRole, bib, 1, Qt.MatchExactly)

        if not index_list:
            raise InputError('Failed to find racer with bib %s' % bib)

        index = index_list[0].siblingAtColumn(self.finish_column)
        self.setData(index, finish)
        self.dataChanged.emit(index, index)

    def set_racer_status(self, bib, status):
        """Set finish time of the racer identified by "bib"."""
        index_list = self.match(self.index(0, self.bib_column),
                                Qt.DisplayRole, bib, 1, Qt.MatchExactly)

        if not index_list:
            raise InputError('Failed to find racer with bib %s' % bib)

        index = index_list[0].siblingAtColumn(self.status_column)
        self.setData(index, status)
        self.dataChanged.emit(index, index)

    def assign_start_times(self, field_name, start, interval, dry_run=False):
        """Assign start times to racers.

        Start times can be for the entire racer table, or it can only apply to racers belonging
        to the specified field. Also, the same start time can be used, or start times can be
        assigned incrementally according to a specified interval (in seconds).

        This method returns the number of racers whose start times would be overwritten.

        If dry_run is true, then no action is taken, but we still return the number of racers
        whose start times would have been overwritten.
        """
        if field_name and not self.modeldb.field_table_model.id_from_name(field_name):
            raise InputError('Invalid field "%s"' % field_name)

        if not isinstance(start, int):
            raise InputError('Invalid start data type "%s".' % type(start))

        if not msecs_is_valid(start):
            raise InputError('Start time is in the past: msecs from reference is "%s".' % start)

        starts_overwritten = 0

        for row in range(self.rowCount()):
            if field_name:
                field_index = self.index(row, self.field_column)
                if not field_name == self.data(field_index):
                    continue

            start_index = self.index(row, self.start_column)
            if not dry_run:
                self.setData(start_index, start)
            elif self.data(start_index) != MSECS_UNINITIALIZED:
                starts_overwritten += 1

            start += interval * 1000 # Interval is in seconds.

        if not dry_run:
            self.dataChanged.emit(QModelIndex(), QModelIndex())

        return starts_overwritten

    def change_reference_clock_datetime(self, old_datetime, new_datetime):
        """Undo old reference clock datetime, and apply new reference clock datetime."""
        # Nothing to do.
        if old_datetime == new_datetime:
            return

        # Accumulate all of the changes and fire them off in one shot.
        self.setEditStrategy(QSqlTableModel.OnManualSubmit)

        delta_msecs = old_datetime.msecsTo(new_datetime)

        for row in range(self.rowCount()):
            index = self.index(row, self.start_column)
            if msecs_is_valid(self.data(index)):
                self.setData(index, self.data(index) - delta_msecs)

            index = self.index(row, self.finish_column)
            if msecs_is_valid(self.data(index)):
                self.setData(index, self.data(index) - delta_msecs)

        self.submitAll()
        self.setEditStrategy(QSqlTableModel.OnFieldChange)

    def racer_count(self):
        """Return total racers in the table."""
        return self.rowCount()

    def racer_count_total_in_field(self, field_name):
        """Return total racers in the table that belong to the specified field."""
        count = 0

        for row in range(self.rowCount()):
            index = self.index(row, self.field_column)

            if self.data(index) == field_name:
                count += 1

        return count

    def racer_count_finished_in_field(self, field_name):
        """Return total finished racers in the table that belong to the specified field."""
        count = 0

        for row in range(self.rowCount()):
            field_index = self.index(row, self.field_column)
            finish_index = self.index(row, self.finish_column)

            if (self.data(field_index) == field_name and
                self.data(finish_index) != MSECS_UNINITIALIZED):
                count += 1

        return count

    def set_remote(self, remote):
        """Do everything needed for a remote that has just been connected."""
        self.remote = remote

        # Make views repaint cell backgrounds to reflect remote.
        self.dataChanged.emit(QModelIndex(), QModelIndex(), [Qt.BackgroundRole])

    def data(self, index, role=Qt.DisplayRole):
        """Color-code the row according to whether the racer has finished or not.

        If a remote is connected, also show a different color for local result vs. result that
        has been submitted successfully to the remote.
        """
        if role == Qt.BackgroundRole:
            brush = None

            record = self.record(index.row())

            column = index.column
            start = record.value(self.START)
            finish = record.value(self.FINISH)

            # No start time. Paint the start time cell red.
            if (column == self.start_column and start == MSECS_UNINITIALIZED):
                brush = QBrush(Qt.red)

            # Finish time is before the start time. Paint the finish time cell red.
            elif (column == self.finish_column and msecs_is_valid(finish) and finish < start):
                brush = QBrush(Qt.red)

            # If there is a remote, paint the row according to status.
            elif self.remote:
                if record.value(self.STATUS) == 'local':
                    brush = QBrush(Qt.yellow)
                elif record.value(self.STATUS) == 'remote':
                    brush = QBrush(Qt.green)
                elif record.value(self.STATUS) == 'rejected':
                    brush = QBrush(Qt.red)
            # No remote. Paint according to whether there is a finish time.
            else:
                if finish != MSECS_UNINITIALIZED:
                    brush = QBrush(Qt.green)

            if brush:
                return brush

        return super().data(index, role)

class ResultTableModel(TableModel):
    """Result Table Model

    This table contains the result scratch pad contents (before they are submitted to the racer
    table). As such, there is a scratch pad field that should eventually be a bib number, but
    until it is submitted to the racer table, can be anything (and is often just blank at first,
    and filled in with a proper bib number later).
    """

    TABLE = 'result'
    ID = 'id'
    SCRATCHPAD = 'scratchpad'
    FINISH = 'finish'

    def __init__(self, modeldb):
        """Initialize the ResultTableModel instance."""
        super().__init__(modeldb)

        self.create_table()

        self.setEditStrategy(QSqlTableModel.OnFieldChange)
        self.setTable(self.TABLE)

        # We need the field index so often, just save them here since they never change.
        self.id_column = self.fieldIndex(self.ID)
        self.scratchpad_column = self.fieldIndex(self.SCRATCHPAD)
        self.finish_column = self.fieldIndex(self.FINISH)

        self.setHeaderData(self.scratchpad_column, Qt.Horizontal, 'Bib')
        self.setHeaderData(self.finish_column, Qt.Horizontal, 'Finish')

        self.select()

    def create_table(self):
        """Create the database table."""
        query = QSqlQuery(self.database())

        if not query.exec(
            'CREATE TABLE IF NOT EXISTS "%s" ' % self.TABLE +
            '("%s" INTEGER NOT NULL PRIMARY KEY, ' % self.ID +
             '"%s" TEXT NOT NULL, ' % self.SCRATCHPAD +
             '"%s" INT NOT NULL);' % self.FINISH):
            raise DatabaseError(query.lastError().text())

        query.finish()

    def add_result(self, scratchpad, finish):
        """Add a row to the database table."""
        record = self.record()
        record.setGenerated(self.ID, False)
        record.setValue(self.SCRATCHPAD, scratchpad)
        record.setValue(self.FINISH, finish)

        self.insertRecord(-1, record)

    def submit_result(self, row):
        """Submit a result to the racer table model, and remove from results table model."""
        record = self.record(row)
        bib = record.value(self.SCRATCHPAD)
        finish = record.value(self.FINISH)

        self.modeldb.racer_table_model.set_racer_finish(bib, finish)
        self.modeldb.racer_table_model.set_racer_status(bib, 'local')
        self.removeRow(row)
