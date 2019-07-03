#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
import traceback
from PyQt5.QtCore import pyqtSignal, QObject, QSettings, QSize, QThread, QTimer, Qt
from PyQt5.QtGui import QBrush, QKeySequence, QPalette
from PyQt5.QtWidgets import QApplication, QDialog, QDockWidget, QMainWindow, QMenuBar, QMessageBox
from PyQt5.QtWidgets import QAbstractScrollArea, QHeaderView, QSizePolicy
from PyQt5.QtWidgets import QFormLayout, QHBoxLayout, QVBoxLayout
from PyQt5.QtWidgets import QCheckBox, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTableWidget
from PyQt5.QtWidgets import QFrame, QTableWidgetItem, QWidget

ORGANIZATION_NAME = 'NVIDIA'
ORGANIZATION_DOMAIN = 'nvidia.com'
APPLICATION_NAME = 'CalibrationTool'
VERSION = '1.0'

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

class CalibrationTool(QObject):
    STATUS_INCOMPLETE = 0
    STATUS_PENDING = 1
    STATUS_IN_PROGRESS = 2
    STATUS_FAILURE = 3
    STATUS_SUCCESS = 4

    OUTPUT_LINE_SUBPROCESS = 0
    OUTPUT_LINE_INFO = 1
    OUTPUT_LINE_WARN = 2
    OUTPUT_LINE_ERROR = 3

    DEFAULT_SUBPROCESS_TIMEOUT = 900 # 15 minutes

    def __init__(self, name):
        super().__init__()

        self.name = name

        self.status = self.STATUS_INCOMPLETE

        # Setup widget. Children of this base class will populate it with stuff.
        self.widget = QWidget()
        self.widget.tool = self

        self.metadata = {}

        # The log dialog. Contains the tool's output.
        self.log_dialog = QDialog()
        self.log_plaintextedit = QPlainTextEdit(self.log_dialog)
        self.log_plaintextedit.setReadOnly(True)
        document = self.log_plaintextedit.document()
        font = document.defaultFont()
        font.setFamily('Courier New')
        document.setDefaultFont(font)
        self.log_dialog.setLayout(QVBoxLayout())
        self.log_dialog.layout().addWidget(self.log_plaintextedit)
        self.output_line.connect(self.handle_output_line)

    def start(self):
        # Clear the output.
        self.log_plaintextedit.setPlainText('')

        # Start a thread to run the "run" method.
        self.thread = QThread()
        self.moveToThread(self.thread)
        self.finished.connect(self.thread.quit)
        self.thread.started.connect(self.run)
        self.thread.finished.connect(self.reset_thread)
        self.thread.start()

    def run(self):
        raise NotImplementedError

    def reset(self):
        self.status = self.STATUS_INCOMPLETE

    def reset_thread(self):
        self.moveToThread(QApplication.instance().thread())

    def change_status(self, status):
        self.status = status
        self.status_changed.emit(self.metadata, self.status)

        if status in (self.STATUS_SUCCESS, self.STATUS_FAILURE):
            self.finished.emit()

    def message(self, msg, kind=OUTPUT_LINE_INFO):
        self.output_line.emit(msg, kind)

    def info(self, msg):
        self.message(msg, self.OUTPUT_LINE_INFO)

    def warn(self, msg):
        self.message(msg, self.OUTPUT_LINE_WARN)

    def error(self, msg):
        self.message(msg, self.OUTPUT_LINE_ERROR)

    # This function takes a list of strings that forms a command invocation, OR
    # it can take a list of such lists. In the latter case, the stdout of the first
    # command will be piped into the stdin of the next command, etc.
    #
    # Note that this method is expected to be run in a separate thread, so this method
    # should not directly do any GUI stuff. Instead, it should use signals to communicate
    # with the main thread.
    def run_subprocess(self, *args, **kwargs):
        cmd = args[0]

        if len(args) == 1:
            rest = None
        else:
            rest = args[1:]

        stdin = kwargs.pop('stdin', None)
        timeout = kwargs.pop('timeout', self.DEFAULT_SUBPROCESS_TIMEOUT)
        if kwargs:
            raise TypeError('Got unexpected keyword argument(s) %s.' %
                            ', '.join(kwargs.keys()))

        if rest:
            with subprocess.Popen(cmd,
                                  stdin=stdin,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL) as process:

                return self.run_subprocess(*rest, stdin=process.stdout,
                                           timeout=timeout)

        p = subprocess.Popen(cmd,
                             stdin=stdin,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             bufsize=1)

        for line in iter(p.stdout.readline, b''):
            decoded_line = line.decode('utf-8').replace('\n', '')
            self.output_line.emit(decoded_line, self.OUTPUT_LINE_SUBPROCESS)

        p.stdout.close()
        p.stderr.close()
        p.wait()

        return p

    def handle_output_line(self, line, kind):
        del kind
        self.log_plaintextedit.appendHtml(line)

    # The status_changed signal is emitted with this instance's metadata dict and the status.
    status_changed = pyqtSignal(dict, int)

    # Emitted when the tool has finished running (i.e. if we have a success or failure status).
    finished = pyqtSignal()

    # Emitted when a line of output is available.
    output_line = pyqtSignal(str, int)

class CalibrationToolIMUBias(CalibrationTool):
    TOOL_NAME = 'IMU Bias'

    DEFAULT_SENSOR_ID = 0

    def __init__(self):
        super().__init__(self.TOOL_NAME)

        # Various parameters of the IMU Bias calibration tool.
        self.widget.sensor_id_lineedit = QLineEdit(str(self.DEFAULT_SENSOR_ID))

        # Lay them out in the widget.
        self.widget.setLayout(QFormLayout())
        self.widget.layout().addRow('IMU Sensor', self.widget.sensor_id_lineedit)

    def run(self):
        self.change_status(self.STATUS_IN_PROGRESS)

        cmd = os.path.join(_SCRIPT_DIR, '..', 'imu_bias', 'self-calibration-imu-bias')
        self.info('Running: %s' % cmd)
        self.info('Params:')
        self.info('--imu-sensor-name=%s' % self.widget.sensor_id_lineedit.text())
        self.run_subprocess(['echo', '.'])
        self.run_subprocess(['sleep', '1'])
        self.run_subprocess(['echo', '.'])
        self.run_subprocess(['sleep', '1'])
        self.run_subprocess(['echo', '.'])
        self.run_subprocess(['sleep', '1'])
        self.info('Done.')

        self.change_status(self.STATUS_SUCCESS)

class CalibrationToolIMU(CalibrationTool):
    TOOL_NAME = 'IMU'

    DEFAULT_SENSOR_ID = 0

    def __init__(self):
        super().__init__(self.TOOL_NAME)

        # Various parameters of the IMU calibration tool.
        self.widget.sensor_id_lineedit = QLineEdit(str(self.DEFAULT_SENSOR_ID))

        # Lay them out in the widget.
        self.widget.setLayout(QFormLayout())
        self.widget.layout().addRow('IMU Sensor', self.widget.sensor_id_lineedit)

    def run(self):
        self.change_status(self.STATUS_IN_PROGRESS)

        cmd = os.path.join(_SCRIPT_DIR, '..', 'imu', 'self-calibration-imu')
        self.info('Running: %s' % cmd)
        self.info('Params:')
        self.info('--imu-sensor=%s' % self.widget.sensor_id_lineedit.text())
        self.run_subprocess(['echo', '.'])
        self.run_subprocess(['sleep', '1'])
        self.run_subprocess(['echo', '.'])
        self.run_subprocess(['sleep', '1'])
        self.run_subprocess(['echo', '.'])
        self.run_subprocess(['sleep', '1'])
        self.info('Done.')

        self.change_status(self.STATUS_SUCCESS)

class CalibrationToolCamera(CalibrationTool):
    TOOL_NAME = 'Camera'

    DEFAULT_SENSOR_ID = 0
    DEFAULT_CAMERA_ROLL = True
    DEFAULT_CAMERA_HEIGHT = True

    def __init__(self):
        super().__init__(self.TOOL_NAME)

        # Various parameters of the camera calibration tool.
        self.widget.sensor_id_lineedit = QLineEdit(str(self.DEFAULT_SENSOR_ID))

        self.widget.camera_roll_checkbox = QCheckBox()
        self.widget.camera_roll_checkbox.setTristate(False)
        if self.DEFAULT_CAMERA_ROLL:
            self.widget.camera_roll_checkbox.setCheckState(Qt.Checked)
        else:
            self.widget.camera_roll_checkbox.setCheckState(Qt.Unchecked)

        self.widget.camera_height_checkbox = QCheckBox()
        self.widget.camera_height_checkbox.setTristate(False)
        if self.DEFAULT_CAMERA_HEIGHT:
            self.widget.camera_height_checkbox.setCheckState(Qt.Checked)
        else:
            self.widget.camera_height_checkbox.setCheckState(Qt.Unchecked)

        # Lay them out in the widget.
        self.widget.setLayout(QFormLayout())
        self.widget.layout().addRow('Camera Sensor', self.widget.sensor_id_lineedit)
        self.widget.layout().addRow('Estimate Camera Roll', self.widget.camera_roll_checkbox)
        self.widget.layout().addRow('Estimate Camera Height', self.widget.camera_height_checkbox)

    def run(self):
        self.change_status(self.STATUS_IN_PROGRESS)

        cmd = os.path.join(_SCRIPT_DIR, '..', 'camera', 'self-calibration-camera')
        self.info('Running: %s' % cmd)
        self.info('Params:')
        self.info('--camera-sensor=%s' % self.widget.sensor_id_lineedit.text())
        if self.widget.camera_roll_checkbox.checkState():
            self.info('--roll-calib=turn')
        if self.widget.camera_height_checkbox.checkState():
            self.info('--height-calib=point')
        self.run_subprocess(['echo', '.'])
        self.run_subprocess(['sleep', '1'])
        self.run_subprocess(['echo', '.'])
        self.run_subprocess(['sleep', '1'])
        self.run_subprocess(['echo', '.'])
        self.run_subprocess(['sleep', '1'])
        self.info('Done.')

        self.change_status(self.STATUS_SUCCESS)

class CalibrationToolLidar(CalibrationTool):
    TOOL_NAME = 'Lidar'

    DEFAULT_SENSOR_ID = 0
    DEFAULT_CAMERA_ROLL = True
    DEFAULT_CAMERA_HEIGHT = True

    def __init__(self):
        super().__init__(self.TOOL_NAME)

        # Various parameters of the lidar calibration tool.
        self.widget.sensor_id_lineedit = QLineEdit(str(self.DEFAULT_SENSOR_ID))

        # Lay them out in the widget.
        self.widget.setLayout(QFormLayout())
        self.widget.layout().addRow('Lidar Sensor', self.widget.sensor_id_lineedit)

    def run(self):
        self.change_status(self.STATUS_IN_PROGRESS)

        cmd = os.path.join(_SCRIPT_DIR, '..', 'lidar', 'self-calibration-lidar')
        self.info('Running: %s' % cmd)
        self.info('Params:')
        self.info('--lidarSensor=%s' % self.widget.sensor_id_lineedit.text())
        self.run_subprocess(['echo', '.'])
        self.run_subprocess(['sleep', '1'])
        self.run_subprocess(['echo', '.'])
        self.run_subprocess(['sleep', '1'])
        self.run_subprocess(['echo', '.'])
        self.run_subprocess(['sleep', '1'])
        self.info('Done.')

        self.change_status(self.STATUS_SUCCESS)

STATUS_MAP = {
    CalibrationTool.STATUS_INCOMPLETE: {'text': 'Incomplete', 'color': Qt.white},
    CalibrationTool.STATUS_PENDING: {'text': 'Pending', 'color': Qt.white},
    CalibrationTool.STATUS_IN_PROGRESS: {'text': 'In Progress', 'color': Qt.yellow},
    CalibrationTool.STATUS_SUCCESS: {'text': 'Success', 'color': Qt.green},
    CalibrationTool.STATUS_FAILURE: {'text': 'Failure', 'color': Qt.red}}

class CalibrationToolSettings(QWidget):
    DEFAULT_SKIP_DEPENDENCIES = Qt.Unchecked
    DEFAULT_HALT_ON_FAILURE = Qt.Checked

    def __init__(self):
        super().__init__()

        self.setWindowTitle('Settings')
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.skip_dependencies_checkbox = QCheckBox('Skip Dependencies')
        self.skip_dependencies_checkbox.setTristate(False)

        self.halt_on_failure_checkbox = QCheckBox('Halt on failure')
        self.halt_on_failure_checkbox.setTristate(False)

        self.setLayout(QVBoxLayout())
        self.layout().addWidget(self.skip_dependencies_checkbox)
        self.layout().addWidget(self.halt_on_failure_checkbox)

        # Restore saved window settings.
        self.read_settings()

    def hideEvent(self, event): #pylint: disable=invalid-name
        del event

        # Save window settings.
        self.write_settings()

    def read_settings(self):
        group_name = type(self).__name__
        settings = QSettings()
        settings.beginGroup(group_name)

        check_state = int(settings.value('skip_dependencies', self.DEFAULT_SKIP_DEPENDENCIES))
        self.skip_dependencies_checkbox.setCheckState(check_state)

        check_state = int(settings.value('halt_on_failure', self.DEFAULT_HALT_ON_FAILURE))
        self.halt_on_failure_checkbox.setCheckState(check_state)

        settings.endGroup()

    def write_settings(self):
        group_name = type(self).__name__
        settings = QSettings()
        settings.beginGroup(group_name)

        settings.setValue('skip_dependencies', self.skip_dependencies_checkbox.checkState())

        settings.setValue('halt_on_failure', self.halt_on_failure_checkbox.checkState())

        settings.endGroup()

class CalibrationToolControls(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle('Controls')
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.run_all_button = QPushButton('Run All')

        self.reset_status_button = QPushButton('Reset Status')

        self.status_label = QLabel()
        self.status_label.setAutoFillBackground(True)
        self.status_label.setFrameStyle(QFrame.Box)

        # Lay them out.
        self.setLayout(QHBoxLayout())
        self.layout().addWidget(self.run_all_button)
        self.layout().addWidget(self.reset_status_button)
        self.layout().addWidget(self.status_label)

        self.set_status(CalibrationTool.STATUS_INCOMPLETE)

        # Restore saved window settings.
        self.read_settings()

    def hideEvent(self, event): #pylint: disable=invalid-name
        del event

        # Save window settings.
        self.write_settings()

    def set_status(self, status):
        self.status_label.setText(STATUS_MAP[status]['text'])

        palette = self.status_label.palette()
        palette.setColor(QPalette.Window, STATUS_MAP[status]['color'])
        self.status_label.setPalette(palette)

    def read_settings(self):
        group_name = type(self).__name__
        settings = QSettings()
        settings.beginGroup(group_name)

        settings.endGroup()

    def write_settings(self):
        group_name = type(self).__name__
        settings = QSettings()
        settings.beginGroup(group_name)

        settings.endGroup()

class CalibrationToolOutput(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle('Output')

        # Button to clear the output window.
        clear_button = QPushButton('Clear')
        clear_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # Output window.
        self.output_plaintextedit = QPlainTextEdit()
        self.output_plaintextedit.setReadOnly(True)
        document = self.output_plaintextedit.document()
        font = document.defaultFont()
        font.setFamily('Courier New')
        document.setDefaultFont(font)

        # Lay them out.
        self.setLayout(QVBoxLayout())
        self.layout().addWidget(clear_button)
        self.layout().addWidget(self.output_plaintextedit)

        # Signals/slots.
        clear_button.clicked.connect(lambda: self.output_plaintextedit.setPlainText(''))

        # Restore saved window settings.
        self.read_settings()

    def hideEvent(self, event): #pylint: disable=invalid-name
        del event

        # Save window settings.
        self.write_settings()

    def append_html(self, line):
        self.output_plaintextedit.appendHtml(line)

    def read_settings(self):
        group_name = type(self).__name__
        settings = QSettings()
        settings.beginGroup(group_name)

        settings.endGroup()

    def write_settings(self):
        group_name = type(self).__name__
        settings = QSettings()
        settings.beginGroup(group_name)

        settings.endGroup()

class CalibrationToolTable(QTableWidget):
    """Show a table of all of the tools and their completion progress.

    The table has the following columns:
        Name
        Status
        Setup button
        Run button
    """
    NAME_COLUMN = 0
    STATUS_COLUMN = 1
    SETUP_COLUMN = 2
    RUN_COLUMN = 3
    LOG_COLUMN = 4
    NUM_COLUMNS = 5

    RUN_TIMER_INTERVAL_SECS = 1

    def __init__(self):
        super().__init__()

        # The run_list is a list of tools that are currently pending to be started.
        # The run_timer is a timer that is only started when the run_list is completely drained, and
        # is used to start the first tool in the run_list.
        self.run_list = []
        self.run_timer = QTimer(self)
        self.run_timer.setInterval(self.RUN_TIMER_INTERVAL_SECS * 1000)
        self.run_timer.setTimerType(Qt.VeryCoarseTimer)
        self.run_timer.setSingleShot(True)
        self.run_timer.timeout.connect(self.check_run_list)
        self.run_timer.start()

        # Whether the tool's dependencies should be scheduled when a tool is started.
        self.skip_dependencies = False

        # Whether we should stop running pending tools on the first failure encountered.
        self.halt_on_failure = False

        # Set up the tool table.
        self.setSelectionMode(QTableWidget.NoSelection)

        # Make it so the entire table is always shown (i.e. no vertical scrolling needed).
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)

        self.setColumnCount(self.NUM_COLUMNS)

        self.setHorizontalHeaderLabels(['Sensor', 'Status', 'Setup', 'Run', 'Log'])
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionsMovable(True)
        self.horizontalHeader().setSectionResizeMode(self.SETUP_COLUMN,
                                                     QHeaderView.ResizeToContents)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        # Instantiate all of our calibration tools.
        imu_bias = CalibrationToolIMUBias()
        imu = CalibrationToolIMU()

        camera = CalibrationToolCamera()
        camera.metadata['dependencies'] = [imu_bias, imu]

        lidar = CalibrationToolLidar()
        lidar.metadata['dependencies'] = [imu_bias, imu]

        self.add_tool(imu_bias)
        self.add_tool(imu)
        self.add_tool(camera)
        self.add_tool(lidar)

        # Restore saved window settings.
        self.read_settings()

    def hideEvent(self, event): #pylint: disable=invalid-name
        del event

        # Save window settings.
        self.write_settings()

    def check_run_list(self):
        if not self.run_list:
            self.run_timer.start()
            return

        # If halt on failure, check to see if there are any failures, and if so, clear the run list.
        if self.halt_on_failure:
            for row in range(self.rowCount()):
                tool = self.cellWidget(row, self.SETUP_COLUMN).tool
                if tool.status == CalibrationTool.STATUS_FAILURE:
                    self.halt()
                    return

        tool = self.run_list[0]
        tool.start()

    def add_to_run_list(self, tool, skip_dependencies=False):
        # Check to see if we're already in the run list.
        for pending_tool in self.run_list:
            if tool == pending_tool:
                return

        if not skip_dependencies and 'dependencies' in tool.metadata:
            for dependent_tool in tool.metadata['dependencies']:
                if dependent_tool.status != CalibrationTool.STATUS_SUCCESS:
                    self.add_to_run_list(dependent_tool, skip_dependencies)

        self.run_list.append(tool)
        row = tool.metadata['row']
        self.set_status(row, CalibrationTool.STATUS_PENDING)

    def remove_from_run_list(self, tool):
        for pending_tool in self.run_list:
            if tool == pending_tool:
                row = tool.metadata['row']
                self.set_status(row, CalibrationTool.STATUS_INCOMPLETE)
                self.run_list.remove(tool)
                return

    def clear_run_list(self):
        while self.run_list:
            tool = self.run_list[0]
            self.remove_from_run_list(tool)

        self.run_timer.start()

    def halt(self):
        self.clear_run_list()

        for row in range(self.rowCount()):
            tool = self.cellWidget(row, self.SETUP_COLUMN).tool
            if tool.status == CalibrationTool.STATUS_PENDING:
                self.set_status(row, CalibrationTool.STATUS_INCOMPLETE)

    def set_status(self, row, status):
        item = self.item(row, self.STATUS_COLUMN)

        item.setText(STATUS_MAP[status]['text'])
        item.setBackground(QBrush(STATUS_MAP[status]['color']))
        item.status = status

        # Calculate combined status.
        num_incomplete = 0
        num_pending = 0
        num_in_progress = 0
        num_failure = 0
        num_success = 0
        for temp_row in range(self.rowCount()):
            tool = self.cellWidget(temp_row, self.SETUP_COLUMN).tool
            if tool.status == CalibrationTool.STATUS_INCOMPLETE:
                num_incomplete += 1
            elif tool.status == CalibrationTool.STATUS_PENDING:
                num_pending += 1
            elif tool.status == CalibrationTool.STATUS_IN_PROGRESS:
                num_in_progress += 1
            elif tool.status == CalibrationTool.STATUS_FAILURE:
                num_failure += 1
            elif tool.status == CalibrationTool.STATUS_SUCCESS:
                num_success += 1

        if num_in_progress:
            status = CalibrationTool.STATUS_IN_PROGRESS
        elif num_failure:
            status = CalibrationTool.STATUS_FAILURE
        elif num_pending:
            status = CalibrationTool.STATUS_PENDING
        elif num_incomplete and not num_pending:
            status = CalibrationTool.STATUS_INCOMPLETE
        else:
            status = CalibrationTool.STATUS_SUCCESS

        self.status_changed.emit(status)

    def get_status(self, row):
        item = self.item(row, self.STATUS_COLUMN)
        return item.status

    def add_tool(self, tool):
        row = self.rowCount()
        self.setRowCount(self.rowCount() + 1)

        # Name column.
        item = QTableWidgetItem(tool.name)
        item.setFlags(item.flags() ^ Qt.ItemIsEditable)
        self.setItem(row, self.NAME_COLUMN, item)

        # Setup column.
        self.setCellWidget(row, self.SETUP_COLUMN, tool.widget)

        # Run column.
        run_button = QPushButton('Run')
        run_button.clicked.connect(lambda: self.handle_tool_start(row))
        self.setCellWidget(row, self.RUN_COLUMN, run_button)

        # Log column.
        log_button = QPushButton('Log')
        log_button.clicked.connect(lambda: self.handle_tool_log(row))
        self.setCellWidget(row, self.LOG_COLUMN, log_button)

        # Completion column.
        item = QTableWidgetItem()
        item.setFlags(item.flags() ^ Qt.ItemIsEditable)
        self.setItem(row, self.STATUS_COLUMN, item)
        self.set_status(row, CalibrationTool.STATUS_INCOMPLETE)

        # Add row metadata to the tool.
        tool.metadata['row'] = row

        # Hook up the signals from each tool.
        tool.status_changed.connect(self.handle_tool_status_changed)
        tool.finished.connect(self.handle_tool_finished)

    def handle_tool_start(self, row):
        tool = self.cellWidget(row, self.SETUP_COLUMN).tool

        self.add_to_run_list(tool, self.skip_dependencies)

    def handle_tool_log(self, row):
        tool = self.cellWidget(row, self.SETUP_COLUMN).tool
        tool.log_dialog.show()

    def handle_tool_status_changed(self, metadata, status):
        self.set_status(metadata['row'], status)

    def handle_tool_finished(self):
        del self.run_list[0]
        self.check_run_list()

    def toggle_skip_dependencies(self, checked):
        self.skip_dependencies = checked

    def toggle_halt_on_failure(self, checked):
        self.halt_on_failure = checked

    def run_all_tools(self):
        self.reset_tool_status()

        for row in range(self.rowCount()):
            run_button = self.cellWidget(row, self.RUN_COLUMN)

            run_button.click()

    def reset_tool_status(self):
        self.clear_run_list()

        for row in range(self.rowCount()):
            self.cellWidget(row, self.SETUP_COLUMN).tool.reset()
            self.set_status(row, CalibrationTool.STATUS_INCOMPLETE)

    def read_settings(self):
        group_name = type(self).__name__
        settings = QSettings()
        settings.beginGroup(group_name)

        if settings.contains('horizontal_header_state'):
            self.horizontalHeader().restoreState(settings.value('horizontal_header_state'))

        settings.endGroup()

    def write_settings(self):
        group_name = type(self).__name__
        settings = QSettings()
        settings.beginGroup(group_name)

        settings.setValue('horizontal_header_state', self.horizontalHeader().saveState())

        settings.endGroup()

    # This signal is emitted when a tool's status has changed. The status that is passed is a
    # combined, lowest-common-denominator status of all of the tools.
    status_changed = pyqtSignal(int)

class CalibrationToolMainWindow(QMainWindow):
    DEFAULT_SIZE = QSize(600, 300)

    def __init__(self):
        super().__init__()

        self.fullscreen = False

        # Set up settings dock widget.
        settings_widget = CalibrationToolSettings()
        settings_dockwidget = QDockWidget(settings_widget.windowTitle(), self)
        settings_dockwidget.setObjectName(settings_widget.windowTitle())
        settings_dockwidget.setWidget(settings_widget)
        self.addDockWidget(Qt.TopDockWidgetArea, settings_dockwidget)

        # Set up controls dock widget.
        controls_widget = CalibrationToolControls()
        controls_dockwidget = QDockWidget(controls_widget.windowTitle(), self)
        controls_dockwidget.setObjectName(controls_widget.windowTitle())
        controls_dockwidget.setWidget(controls_widget)
        self.addDockWidget(Qt.TopDockWidgetArea, controls_dockwidget)

        # Set up output dock widget.
        self.output_widget = CalibrationToolOutput()
        output_dockwidget = QDockWidget(self.output_widget.windowTitle(), self)
        output_dockwidget.setObjectName(self.output_widget.windowTitle())
        output_dockwidget.setWidget(self.output_widget)
        self.addDockWidget(Qt.BottomDockWidgetArea, output_dockwidget)

        # Set up central widget.
        table_widget = CalibrationToolTable()
        self.setCentralWidget(table_widget)

        # Set up menubar.
        menubar = QMenuBar()
        self.setMenuBar(menubar)

        file_menu = self.menuBar().addMenu('&File')
        file_menu.addAction('&Quit', self.close, QKeySequence.Quit)

        tools_menu = self.menuBar().addMenu('&Tools')
        settings_menu_action = tools_menu.addAction('&Settings')
        settings_menu_action.setCheckable(True)
        controls_menu_action = tools_menu.addAction('&Controls')
        controls_menu_action.setCheckable(True)
        output_menu_action = tools_menu.addAction('&Output')
        output_menu_action.setCheckable(True)

        # Hook up signals/slots.
        settings_dockwidget.visibilityChanged.connect(settings_menu_action.setChecked)
        settings_menu_action.toggled.connect(settings_dockwidget.setVisible)

        controls_dockwidget.visibilityChanged.connect(controls_menu_action.setChecked)
        controls_menu_action.toggled.connect(controls_dockwidget.setVisible)

        output_dockwidget.visibilityChanged.connect(output_menu_action.setChecked)
        output_menu_action.toggled.connect(output_dockwidget.setVisible)

        settings_widget.skip_dependencies_checkbox.toggled.connect(
            table_widget.toggle_skip_dependencies)
        table_widget.toggle_skip_dependencies(
            settings_widget.skip_dependencies_checkbox.isChecked())

        settings_widget.halt_on_failure_checkbox.toggled.connect(
            table_widget.toggle_halt_on_failure)
        table_widget.toggle_halt_on_failure(
            settings_widget.halt_on_failure_checkbox.isChecked())

        controls_widget.run_all_button.clicked.connect(table_widget.run_all_tools)

        controls_widget.reset_status_button.clicked.connect(table_widget.reset_tool_status)

        for row in range(table_widget.rowCount()):
            tool = table_widget.cellWidget(row, table_widget.SETUP_COLUMN).tool
            tool.output_line.connect(self.handle_output_line)

        table_widget.status_changed.connect(controls_widget.set_status)

        # Restore saved window settings.
        self.read_settings()

    def hideEvent(self, event): #pylint: disable=invalid-name
        del event

        # Save window settings.
        self.write_settings()

    def showFullScreen(self): #pylint: disable=invalid-name
        # Remember that we are in full screen mode. We don't save our main window's geometry in this
        # case.
        self.fullscreen = True

        super().showFullScreen()

    def handle_output_line(self, line, kind):
        if kind == CalibrationTool.OUTPUT_LINE_INFO:
            self.output_widget.append_html('<p style="color:green;">' + line + '</p>')
        elif kind == CalibrationTool.OUTPUT_LINE_WARN:
            self.output_widget.append_html('<p style="color:orange;">' + line + '</p>')
        elif kind == CalibrationTool.OUTPUT_LINE_ERROR:
            self.output_widget.append_html('<p style="color:red;">' + line + '</p>')
        else:
            self.output_widget.append_html(line)

    def read_settings(self):
        group_name = type(self).__name__
        settings = QSettings()
        settings.beginGroup(group_name)

        if settings.value('geometry'):
            self.restoreGeometry(settings.value('geometry'))

        if settings.value('windowState'):
            self.restoreState(settings.value('windowState'))

        settings.endGroup()

    def write_settings(self):
        group_name = type(self).__name__
        settings = QSettings()
        settings.beginGroup(group_name)

        if not self.fullscreen:
            settings.setValue('geometry', self.saveGeometry())
        settings.setValue('windowState', self.saveState())

        settings.endGroup()

def excepthook(exc_type, exc_value, exc_traceback):
    """Show the exception in an error dialog.

    Also, call the old except hook to get the normal behavior as well.
    """
    if _old_excepthook:
        _old_excepthook(exc_type, exc_value, exc_traceback)

    exception_str = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    QMessageBox.critical(None, exc_type.__name__,
                         'Unhandled exception:\n\n%s' % exception_str)

    sys.exit(-1)

# Install our custom exception hook.
_old_excepthook = sys.excepthook #pylint: disable=invalid-name
sys.excepthook = excepthook

def main():
    parser = argparse.ArgumentParser(description=APPLICATION_NAME)
    parser.add_argument('--version', action='version', version=APPLICATION_NAME + ' v' + VERSION)
    parser.add_argument('--fullscreen', action='store_true')

    args = parser.parse_args()

    QApplication.setOrganizationName(ORGANIZATION_NAME)
    QApplication.setOrganizationDomain(ORGANIZATION_DOMAIN)
    QApplication.setApplicationName(APPLICATION_NAME)
    QApplication.setApplicationVersion(VERSION)

    app = QApplication(sys.argv)

    main_window = CalibrationToolMainWindow()

    if args.fullscreen:
        main_window.showFullScreen()
    else:
        main_window.show()

    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
