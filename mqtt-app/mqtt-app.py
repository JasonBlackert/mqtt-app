import re
import sys
import time
from datetime import datetime
import json
import logging
import numpy as np

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from PyQt5.QtCore import pyqtSignal, QThread, QTimer
from PyQt5.QtGui import QFont, QIcon, QColor, QBrush
from PyQt5.QtWidgets import QApplication, QMainWindow, QTabWidget, QDialog, QAction
from PyQt5.QtWidgets import QVBoxLayout, QGridLayout, QTableWidget, QTableWidgetItem
from PyQt5.QtWidgets import QPushButton, QComboBox, QCheckBox, QLineEdit, QLabel

from broker import MQTT_Broker
from config import parse_args

args = parse_args()
config = args.config

log = logging.getLogger(__name__)
logging.basicConfig(level="INFO", format="%(name)s [%(levelname)s]: %(message)s")


class SolarLEAF:
    def __init__(self, gateway, macaddr, index):
        self.index = index
        self.mac = macaddr
        self.gateway = gateway
        self.time = time.time()

        self.BMS_SOC = 0.0
        self.BMS_Min_Cell_V = self.BMS_Max_Cell_V = 0.0
        self.VPV = self.IPV = self.P_PV = 0.0
        self.VBAT = self.IBAT = self.P_BAT = 0.0
        self.VOUT = self.IOUT = self.P_OUT = 0.0
        self.VCOM = self.VOUT_X = 0.0
        self.FET_T = self.TEMP_PCB = 0.0

        self.sl_status = self.FW_CRC = self.VERSION = self.bmsversion = ""

        self.last = time.time()

    def items(self):
        self.time = time.strftime("%H:%M:%S", time.localtime())
        items = [
            f"{self.index:>2}",
            f"{self.time:<8}",
            f"{self.gateway}",
            f"{self.mac:<12}",
            f"{self.BMS_SOC:5.1f}%",
            f"{self.BMS_Min_Cell_V:5.2f}V",
            f"{self.BMS_Max_Cell_V:5.2f}V",
            f"{self.VPV:5.1f}V",
            f"{self.IPV:6.1f}A",
            f"{self.P_PV:6.1f}W",
            f"{self.VBAT:5.1f}V",
            f"{self.IBAT:6.1f}A",
            f"{self.P_BAT:6.1f}W",
            f"{self.VOUT:5.1f}V",
            f"{self.IOUT:6.1f}A",
            f"{self.P_OUT:6.1f}W",
            f"{self.VCOM:5.1f}V",
            f"{self.VOUT_X:5.1f}V",
            f"{self.FET_T:5.1f}C",
            f"{self.TEMP_PCB:5.1f}C",
            f"{self.sl_status:>2}",
            f"{self.FW_CRC}",
            f"{self.VERSION}",
            # f"{self.bmsversion}",
        ]
        return items


class MainWindow(QMainWindow):
    TIMEOUT = 65

    FONT_SIZE = 8
    FONT = QFont("Courier")
    FONT.setPointSize(FONT_SIZE)

    def __init__(self):
        super().__init__()

        self.brokers = self._init_brokers()
        self.tabs: dict[int, str] = dict()
        self.timers: dict[str, QTimer] = dict()
        self.tables: dict[int, QTableWidget] = dict()
        self.threads: dict[str, UpdateTableThread] = dict()

        self._initUI()

        self.popup_add()

    def _init_brokers(self) -> dict[str, MQTT_Broker]:
        brokers: dict[str:MQTT_Broker] = dict()
        broker_dict = config["gateways"]
        for name, host in broker_dict.items():
            try:
                broker = MQTT_Broker(broker_dict[f"{name}"])
                broker.start()
            except Exception as err:
                log.info(f"Couldn't connect to {name}@{host} error: {err}")
            else:
                brokers[f"{name}"] = broker

        return brokers

    def _initUI(self):
        # Set Title
        self.setWindowTitle("Yotta Asset Manager")
        self.setWindowIcon(QIcon("share/shield.png"))

        # Create and configure a tab widget
        self.tabMenu = QTabWidget(tabsClosable=True, tabCloseRequested=self.close_tab)

        self.setCentralWidget(self.tabMenu)

        # File Menu
        fMenu = self.menuBar().addMenu("File")
        fMenu.addAction(QAction("Add Gateway", self, triggered=self.popup_add))

        # Command Menu
        cMenu = self.menuBar().addMenu("Command")
        cMenu.addAction(QAction("Find Unit", self, triggered=self.popup_find))
        cMenu.addAction(QAction("Plot Fast", self, triggered=self.popup_fast))
        cMenu.addAction(QAction("Update Unit", self, triggered=self.popup_update))
        cMenu.addAction(QAction("Change SSID", self, triggered=self.popup_ssid))
        cMenu.addAction(QAction("Set Parameters", self, triggered=self.popup_parameter))

        pMenu = self.menuBar().addMenu("Print")
        checkboxAction = QAction("Toggle Printing", self)
        checkboxAction.triggered.connect(lambda: self.print_type("print"))
        checkboxAction.setCheckable(True)
        pMenu.addAction(checkboxAction)
        self.print = False

        pMenu.addAction(
            QAction("Get ID (MAC)", self, triggered=lambda: self.print_type("getid"))
        )
        pMenu.addAction(
            QAction(
                "Get SL Status", self, triggered=lambda: self.print_type("sl_status")
            )
        )

        pMenu.addAction(
            QAction("ESP32 Version", self, triggered=lambda: self.print_type("version"))
        )
        pMenu.addAction(
            QAction("S32 Version", self, triggered=lambda: self.print_type("fw_crc"))
        )

        pMenu.addAction(
            QAction("BMS Version", self, triggered=lambda: self.print_type("BMS"))
        )

        # Set Geometry
        self.dialog_geometry = (100, 200, 300, 100)
        self.window_geometry = (100, 100, 1500, 500)
        self.setGeometry(*self.window_geometry)

        # Start Timer to Update Window Every Second
        # timer = QTimer()
        # timer.timeout.connect(self.update_window)
        # timer.start(1000)  # Update every second

    def add_item_to_table(self, gateway, leaf):
        # Add a new item to the table widget
        item = leaf.items()
        if gateway not in self.tabs.values():
            return

        table = self.tables[gateway]
        index = int(item.pop(0)) - 1  # Remove index from items

        # Implement New Entry
        if index >= table.rowCount():
            table.setRowCount(index + 1)

        # Update Entry Based on leaf.index
        for i, value in enumerate(item):
            currEntry = QTableWidgetItem(str(value))
            currEntry.setFont(self.FONT)
            table.setItem(index, i, currEntry)

        # Resize to Contents
        table.resizeRowsToContents()
        table.resizeColumnsToContents()
        # self.adjustSize()

    def add_tab(self, index):
        # Track Current Tab Based on Index
        self.gw_dialog.accept()
        gateway = self.combo_box.currentText()
        self.tabs[index] = gateway

        table = QTableWidget(itemClicked=self.selected_unit)
        self.tables[gateway] = table
        self.tabMenu.addTab(table, gateway)

        # Style and Fonts
        table.setColumnCount(len(config["list"]["header"]))
        table.setHorizontalHeaderLabels(config["list"]["header"])
        style = "background-color: rgb(200, 200, 200); border: none;"
        table.setStyleSheet(f"QHeaderView::section { {style}}")
        table.setShowGrid(False)
        table.horizontalHeader().setFont(self.FONT)
        font = table.horizontalHeader().font()
        font.setBold(True)
        table.horizontalHeader().setFont(font)

        # Initialize Specific Broker
        broker = self.brokers[gateway]
        thread = UpdateTableThread(self, broker, gateway, self.tabs)
        thread.slow_signal.connect(self.add_item_to_table)
        thread.start()
        self.threads[gateway] = thread

        # Resize to Contents
        table.resizeRowsToContents()
        table.resizeColumnsToContents()
        # self.adjustSize()

        # Set New Tab as Current Tab
        self.tabMenu.setCurrentIndex(self.tabMenu.count() - 1)

        # QTimer to update table to red after 60 secs
        # Set up the timer to update the plot in real time
        timer = QTimer()
        timer.timeout.connect(lambda: self.set_timeout_color(gateway))
        timer.start(1000)  # Update every second
        self.timers[gateway] = timer

    def close_tab(self, index):
        # Get the widget of the closed tab
        if not self.tabs:
            return

        thread = self.threads[self.tabs[index]]
        if thread.isFinished:
            thread.quit()

        gateway = self.tabs[index]
        timer = self.timers[gateway]
        timer.stop()

        del self.timers[gateway]
        del self.tabs[index]
        new_tabs: dict = dict()

        for key, value in self.tabs.items():
            if key > 0:
                new_tabs[key - 1] = value
            else:
                new_tabs[key] = value

        self.tabs = new_tabs
        self.tabMenu.removeTab(index)

    def popup_add(self):
        self.gw_dialog = QDialog(self)

        self.combo_box = QComboBox()
        for gateway, broker in self.brokers.items():
            if not gateway in self.tabs.values():
                self.combo_box.addItem(gateway)

        button = QPushButton("Select")
        button.clicked.connect(lambda: self.add_tab(self.tabMenu.count()))

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Select Gateway"))
        layout.addWidget(self.combo_box)
        layout.addWidget(button)

        self.gw_dialog.setGeometry(*self.dialog_geometry)
        self.gw_dialog.setWindowTitle("Gateway")
        self.gw_dialog.setLayout(layout)
        self.gw_dialog.exec_()

    def popup_find(self):
        self.sl_dialog = QDialog(self)
        self.sl_dialog.setWindowTitle("Find Unit")
        self.sl_dialog.setGeometry(*self.dialog_geometry)
        self.sl_dialog.setWindowIcon(QIcon("share/chicken.png"))

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Enter SolarLeaf"))
        layout.addWidget(QLineEdit("24d7eb516930"))
        layout.addWidget(QPushButton("Select", clicked=self.search_for_unit))

        self.sl_dialog.setLayout(layout)
        self.sl_dialog.exec_()

    def popup_fast(self):
        data = self.selected_unit()
        if not data:
            return

        gateway, mac = (data[0], data[1])
        broker = self.brokers[gateway]

        broker.publish(f"Yotta/{mac}/cmd", payload="set fast_period 1")
        log.info(f"Enabled fast data on {mac}")

        data_thread = self.threads[gateway]
        dialog = FastDataDialog(data_thread, mac)
        dialog.exec_()
        time.sleep(1)

        broker.publish(f"Yotta/{mac}/cmd", payload="set fast_period 0")
        log.info(f"Disabled fast data on {mac}")

    def popup_ssid(self):
        data = self.selected_unit()
        if not data:
            return

        self.ssid_dialog = QDialog(self)
        self.ssid_dialog.setWindowTitle("Change SSID")
        self.ssid_dialog.setGeometry(*self.dialog_geometry)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Enter New SSID"))
        layout.addWidget(QLineEdit(""))
        layout.addWidget(QPushButton("Select", clicked=self.change_ssid))

        self.ssid_dialog.setLayout(layout)
        self.ssid_dialog.exec_()

    def popup_warning(self):
        self.warning_dialog = QDialog(self)
        self.warning_dialog.setWindowTitle("SolarLeaf")
        self.warning_dialog.setGeometry(*self.dialog_geometry)

        layout = QGridLayout()
        commit = QPushButton("Commit", clicked=lambda: self.warning("Commit"))
        cancel = QPushButton("Cancel", clicked=lambda: self.warning("Cancel"))
        layout.addWidget(QLabel("Are you sure?"), 0, 0, 0, 1)
        layout.addWidget(commit, 1, 1)
        layout.addWidget(cancel, 2, 1)
        self.warning_dialog.setLayout(layout)
        self.warning_dialog.exec_()

        return self.decision

    def popup_parameter(self):
        data = self.selected_unit()
        if not data:
            return

        self.parameter_dialog = QDialog(self)
        self.parameter_dialog.setWindowTitle("Set Parameters")
        self.parameter_dialog.setGeometry(*self.dialog_geometry)

        layout = QGridLayout()

        portLine = QLineEdit()
        portLine.setPlaceholderText("Port Number")

        portComboBox = QComboBox()
        portComboBox.addItem("port_on")
        portComboBox.addItem("port_off")

        portButton = QPushButton(
            "Send", clicked=lambda: self.set_unit_parameters("port")
        )

        poutLine = QLineEdit()
        poutLine.setPlaceholderText("Set P_OUT Value")

        poutComboBox = QComboBox()
        poutComboBox.addItem("P_OUT_MIN")
        poutComboBox.addItem("P_OUT_MAX")

        poutButton = QPushButton(
            "Send", clicked=lambda: self.set_unit_parameters("pout")
        )

        layout.addWidget(portLine, 0, 0)
        layout.addWidget(portComboBox, 0, 1)
        layout.addWidget(portButton, 0, 2)
        layout.addWidget(poutLine, 1, 0)
        layout.addWidget(poutComboBox, 1, 1)
        layout.addWidget(poutButton, 1, 2)

        self.parameter_dialog.setLayout(layout)
        self.parameter_dialog.exec_()

    def popup_update(self):
        data = self.selected_unit()
        if not data:
            return

        self.update_dialog = QDialog(self)
        self.update_dialog.setWindowTitle("Update Unit")
        self.update_dialog.setGeometry(*self.dialog_geometry)

        layout = QGridLayout()
        labelS32 = QLineEdit()
        labelS32.setPlaceholderText("S32K.bin")
        updateS32 = QPushButton(
            "Update S32K", clicked=lambda: self.update_firmware("S32K")
        )
        labelESP32 = QLineEdit()
        labelESP32.setPlaceholderText("ESP32.bin")
        updateESP32 = QPushButton(
            "Update ESP32", clicked=lambda: self.update_firmware("ESP32")
        )
        labelBMS = QLineEdit()
        labelBMS.setPlaceholderText("BMS.bin")
        updateBMS = QPushButton(
            "Update BMS", clicked=lambda: self.update_firmware("BMS")
        )

        layout.addWidget(labelS32, 0, 0)
        layout.addWidget(updateS32, 0, 1)
        layout.addWidget(labelESP32, 1, 0)
        layout.addWidget(updateESP32, 1, 1)
        layout.addWidget(labelBMS, 2, 0)
        layout.addWidget(updateBMS, 2, 1)
        self.update_dialog.setLayout(layout)
        self.update_dialog.exec_()

    ### HELPER FUNCTIONS ###
    def set_timeout_color(self, gateway):
        table = self.tables[gateway]

        for i in range(table.rowCount()):
            mac = table.item(i, 1).text()

            time_index = 0  # len(config["list"]["header"]) - 1
            time_str = table.item(i, time_index).text()
            date_obj = datetime.combine(
                datetime.today(),
                datetime.strptime(time_str, "%H:%M:%S").time(),
            )
            last_time = int(date_obj.timestamp())

            diff_time = time.time() - last_time
            if diff_time > self.TIMEOUT:
                for j in range(table.columnCount()):
                    table.item(i, j).setForeground(QBrush(QColor(255, 0, 0)))
            else:
                for j in range(table.columnCount()):
                    table.item(i, j).setForeground(QBrush(QColor(0, 0, 0)))

    def search_for_unit(self):
        mac_to_find = self.sl_dialog.findChild(QLineEdit).text()
        if len(mac_to_find) != 12:
            log.info("MAC Address Length Not Correct")
            return

        # Continue Because Input is Valid
        self.sl_dialog.accept()

        # return mac

        log.info(f"Looking for mac: {mac_to_find}")

        for gateway, broker in self.brokers.items():
            broker.publish("Yotta/cmd", "getid")

            time.sleep(5)
            while not broker.queue.empty():
                msg = broker.get()
                mac = msg_parts = msg.topic.split("/")[1]
                if mac == mac_to_find:
                    self.found_on_gateway = gateway
                    log.info(f"Found {mac_to_find} on {self.found_on_gateway}")
                    return self.found_on_gateway
                else:
                    log.info(f"{gateway} - {mac} does not match {mac_to_find}")

        log.info(f"{mac_to_find} not found on any gateway")

    def selected_unit(self):
        current_index = self.tabMenu.currentIndex()
        if current_index == -1:
            log.info("Add a tab and select a row to continue")
            return

        gateway = self.tabs[current_index]
        table = self.tables[gateway]

        selected = table.selectedItems()
        if not len(selected) > 0:
            log.info("No row selected.")
            return

        row = selected[0].row()
        cols = table.columnCount()
        items = [table.item(row, col).text() for col in range(cols)]

        log.info(f"Selected {items[1]} on row {row+1} on {items[0]}")
        return items

    def change_ssid(self):
        ssid = self.ssid_dialog.findChild(QLineEdit).text()
        if ssid == "":
            log.info("Enter a valid SSID")
            return

        self.popup_warning()

        if not self.decision:
            log.info("Operation aborted")
            return

        data = self.selected_unit()
        if not data:
            return

        self.ssid_dialog.accept()

        gateway, mac = (data[0], data[1])
        broker = self.brokers[gateway]

        log.info(f"Changing SSID of {mac} to '{ssid}'")

        broker.publish(f"Yotta/{mac}/cmd", payload=f"inv ssid {ssid}")
        time.sleep(3)
        broker.publish(f"Yotta/{mac}/cmd", payload=f"inv commit")

    def warning(self, decision="Cancel"):
        self.warning_dialog.accept()

        log.info(decision, decision == "Commit")
        if decision == "Commit":
            self.decision = True
        elif decision == "Cancel":
            self.decision = False

    def print_type(self, text):
        current_index = self.tabMenu.currentIndex()
        try:
            gateway = self.tabs[current_index]
            broker = self.brokers[gateway]
        except:
            pass
        else:
            if text == "print":
                self.print = not self.print
                log.info(f"Print Toggle: {self.print}")
            if text == "getid":
                broker.publish(f"Yotta/cmd", payload="getid")
            if text == "version":
                broker.publish(f"Yotta/cmd", payload="version")
            if text == "fw_crc":
                broker.publish(f"Yotta/cmd", payload="get FW_CRC")
            if text == "BMS":
                broker.publish(f"Yotta/cmd", payload="")
            if text == "sl_status":
                broker.publish(f"Yotta/cmd", payload="get sl_status")

    def update_firmware(self, name=""):
        data = self.selected_unit()
        if not data:
            return

        gateway, mac = (data[0], data[1])
        broker = self.brokers[gateway]
        binary_obj = self.update_dialog.findChildren(QLineEdit)
        binary = [obj.text() for obj in binary_obj]

        if not binary:
            return
        if ".bin" not in binary:
            log.info("Invalid Binary File(s)")
            return

        log.info(f"Updating {name} of {mac} to '{binary}'")

        if binary == "":  # Redundant
            return

        if name == "S32K":
            broker.publish(f"Yotta/{mac}/cmd", payload=f"pcimage {binary}")
            time.sleep(3)
            broker.publish(f"Yotta/{mac}cmd", payload=f"pcupdate")
        elif name == "ESP32":
            broker.publish(f"Yotta/{mac}/cmd", payload=f"ota {binary}")
        elif name == "BMS":
            broker.publish(f"Yotta/{mac}/cmd", payload=f"bmsimage {binary}")
            time.sleep(3)
            broker.publish(f"Yotta/{mac}/cmd", payload=f"bmsupdate")

        # self.update_dialog.accept()

    def set_unit_parameters(self, name):
        data = self.selected_unit()
        if not data:
            return

        gateway, mac = (data[0], data[1])
        broker = self.brokers[gateway]

        comboboxes = [
            obj.currentText() for obj in self.parameter_dialog.findChildren(QComboBox)
        ]
        linedit = [obj.text() for obj in self.parameter_dialog.findChildren(QLineEdit)]

        if name == "port":
            state = comboboxes[0]
            number = linedit[0]
        if name == "pout":
            state = comboboxes[1]
            number = linedit[1]

        if type(number) != int:
            log.info(f"value for {state} is not an integer")

        cmd = f"{state} {number}"
        log.info(f"Setting {cmd} on {mac}")
        broker.publish(f"Yotta/{mac}/cmd", payload=cmd)


class UpdateTableThread(QThread):
    slow_signal = pyqtSignal(str, SolarLEAF)
    plot_signal = pyqtSignal(str, SolarLEAF)

    def __init__(self, window, broker, gateway, tabs):
        super().__init__()

        self.window = window
        self.broker = broker
        self.gateway = gateway
        self.tabs = tabs

        self.Leaves: dict[str, SolarLEAF] = dict()

    def run(self):
        while True:
            if self.gateway not in self.tabs.values():
                print(f"Thread terminated for {self.gateway}")
                return

            try:
                data = self.broker.get()
                speed, items = self.process(self.gateway, data)
            except Exception as err:
                print(f"UpdateTable Error: {err}")
            else:
                if not items:
                    break

                if speed == "fast":
                    self.plot_signal.emit(self.gateway, items)
                self.slow_signal.emit(self.gateway, items)

                time.sleep(0.1)

    def process(self, gateway, msg):
        if not re.match("Yotta/............/", msg.topic):
            return

        mac = msg.topic.split("/")[1]
        payload = json.loads(msg.payload)
        speed = payload.get("type", "")

        if self.window.print:
            print(payload)

        # Associate SolarLeaf with Gateway
        index = len(self.Leaves) + 1
        leaf = self.Leaves.setdefault(mac, SolarLEAF(gateway, mac, index))
        leaf.last = time.time()

        [self.set_key(leaf, payload, name) for name in config["list"]["names"]]

        return speed, leaf

    def set_key(self, leaf, data, name: str):
        if name in data.keys():
            setattr(leaf, name, data[name])


class FastDataDialog(QDialog):
    def __init__(self, thread, mac, parent=None):
        super(FastDataDialog, self).__init__(parent)

        self.setWindowTitle(f"Fast Data: {mac}")
        self.setWindowIcon(QIcon("share/shield.png"))

        thread.plot_signal.connect(self.update_plot)

        self.data = [[], [], [], [], [], [], [], [], [], []]

        self.labels = [
            "self.VPV",
            "self.IPV",
            "self.P_PV",
            "self.VBAT",
            "self.IBAT",
            "self.P_BAT",
            "self.VOUT",
            "self.IOUT",
            "self.P_OUT",
            "self.VCOM",
        ]

        # Set up the Matplotlib figure and canvas
        self.figure = Figure(figsize=(1, 1), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        self.axes = self.figure.add_subplot(111)

        # Create Axes
        self.lines: dict = dict()
        for i, name in enumerate(self.labels):
            self.lines[i] = self.create_axes(label=name)

        # Add legend
        self.axes.legend()

        # Set up the layout
        self.layout = QVBoxLayout()
        self.layout.addWidget(self.canvas)

        # Create Checkboxes
        self.checkboxes: dict = dict()
        for i, name in enumerate(self.labels):
            self.checkboxes[i] = self.create_checkbox(label=name)

        self.setLayout(self.layout)
        self.resize(500, 500)

    def create_axes(self, label=""):
        return self.axes.plot([], [], label=label)

    def create_checkbox(self, label=""):
        checkbox = QCheckBox(label)
        checkbox.setChecked(False)
        checkbox.stateChanged.connect(self.visibility)
        self.layout.addWidget(checkbox)
        return checkbox

    def convert_to_float(self, value):
        return float(value.strip(" ").strip("W").strip("V").strip("A"))

    def update_plot(self, gateway, leaf):
        # Append New Data
        new_data = leaf.items()
        for i, data in enumerate(new_data[6:16]):
            self.data[i].append(self.convert_to_float(data))

        # Set New Data
        length = np.arange(len(self.data[0]))
        for i, line in self.lines.items():
            if self.checkboxes[i]:
                line[0].set_data(length, self.data[i])
            else:
                line.set_data([], [])

        # Update
        self.axes.relim()
        self.axes.autoscale_view()
        self.canvas.draw()

    def visibility(self):
        # Change Visibility on Plot
        for i, line in self.lines.items():
            line[0].set_visible(self.checkboxes[i].isChecked())

        self.canvas.draw()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
