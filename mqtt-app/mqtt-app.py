import re
import sys
import time
import json
import logging
import numpy as np

from typing import Dict

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from PyQt5.QtCore import pyqtSignal, QThread, QTimer
from PyQt5.QtGui import QFont

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QComboBox,
    QCheckBox,
    QLineEdit,
    QDialog,
    QLabel,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QAction,
    QVBoxLayout,
    QHBoxLayout,
)

from broker import MQTT_Broker
from config import parse_args

args = parse_args()
config = args.config

lvl = "INFO"
log = logging.getLogger(__name__)
logging.basicConfig(level=lvl, format="%(name)s [%(levelname)s]: %(message)s")


TIMEOUT = 65

FONT_SIZE = 8
FONT = QFont("Courier")
FONT.setPointSize(FONT_SIZE)


class Commands:
    def enable_fast(self, broker, mac):
        # broker.publish(f"Yotta/'{mac}'/cmd", payload="fast 1")
        broker.publish(f"Yotta/{mac}/cmd", payload="set fast_period 1")
        pass

    def disable_fast(self, broker, mac):
        # broker.publish(f"Yotta/'{mac}'/cmd", payload="fast 0")
        broker.publish(f"Yotta/{mac}/cmd", payload="set fast_period 0")
        pass


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

    def items(self):
        self.time = time.strftime("%H:%M:%S", time.localtime())
        items = [
            f"{self.index:>2}",
            f"{self.gateway}",
            f"{self.mac:<12}",
            f"{self.BMS_SOC:5.1f}%",
            f"{self.BMS_Min_Cell_V:5.1f}V",
            f"{self.BMS_Max_Cell_V:5.1f}V",
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
            f"{self.time:<8}",
        ]
        return items


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.cmds = Commands()
        self.brokers = self._init_brokers()
        self.tabs: dict[int, str] = dict()
        self.tables: dict[int, QTableWidget] = dict()
        self.threads: dict[str, UpdateTableThread] = dict()

        self._initUI()

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
        self.setWindowTitle("On the Wall")

        # Create and configure a tab widget
        self.tabMenu = QTabWidget(
            tabsClosable=True, tabCloseRequested=self.close_tab
        )
        self.setCentralWidget(self.tabMenu)

        # File Menu
        fMenu = self.menuBar().addMenu("File")
        fMenu.addAction(QAction("Add Gateway", self, triggered=self.add_popup))

        # Command Menu
        cmdMenu = self.menuBar().addMenu("Command")
        cmdMenu.addAction(QAction("Find Unit", self, triggered=self.find_popup))
        cmdMenu.addAction(QAction("Plot Fast", self, triggered=self.plot_fast))

        # Set Geometry
        self.setGeometry(100, 100, 1400, 400)

    def add_popup(self):
        self.gw_dialog = QDialog(self)
        self.gw_dialog.setWindowTitle("Gateway")
        self.gw_dialog.setGeometry(100, 200, 300, 100)

        combo_box = QComboBox()
        for gateway, broker in self.brokers.items():
            combo_box.addItem(gateway)

        button = QPushButton("Select")
        button.clicked.connect(lambda: self.add_tab(self.tabMenu.count()))

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Select Gateway"))
        layout.addWidget(combo_box)
        layout.addWidget(button)

        self.gw_dialog.setLayout(layout)
        self.gw_dialog.exec_()

    def add_tab(self, index):
        # Track Current Tab Based on Index
        self.gw_dialog.accept()
        gateway = self.gw_dialog.findChild(QComboBox).currentText()
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
        table.horizontalHeader().setFont(FONT)
        font = table.horizontalHeader().font()
        font.setBold(True)
        table.horizontalHeader().setFont(font)

        # Initialize Specific Broker
        broker = self.brokers[gateway]
        thread = UpdateTableThread(broker, gateway, self.tabs)
        thread.slow_signal.connect(self.add_item_to_table)
        thread.start()
        self.threads[gateway] = thread

        # Set New Tab as Current Tab
        self.tabMenu.setCurrentIndex(self.tabMenu.count() - 1)

    def add_item_to_table(self, gateway, item):
        # Add a new item to the table widget
        if gateway not in self.tabs.values():
            return

        table = self.tables[gateway]
        index = int(item.pop(0)) - 1

        # Implement New Entry
        if index >= table.rowCount():
            table.setRowCount(index + 1)

        # Update Entry Based on leaf.index
        for i, value in enumerate(item):
            currEntry = QTableWidgetItem(str(value))
            currEntry.setFont(FONT)
            table.setItem(index, i, currEntry)  # i-1 to not display index

        # Resize to Contents
        table.resizeRowsToContents()
        table.resizeColumnsToContents()

    def close_tab(self, index):
        # Get the widget of the closed tab
        if not self.tabs:
            return

        thread = self.threads[self.tabs[index]]
        if thread.isFinished:
            thread.quit()

        self.tabMenu.removeTab(index)
        del self.tabs[index]
        for key, value in self.tabs.items():
            key -= 1

    def curr_tab(self, tab_index):
        current_index = self.tabMenu.currentIndex()
        try:
            print(current_index, self.tabs[tab_index])
        except:
            pass
        else:
            return current_index == tab_index

    def find_popup(self):
        self.sl_dialog = QDialog(self)
        self.sl_dialog.setWindowTitle("SolarLeaf")
        self.sl_dialog.setGeometry(100, 200, 300, 100)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Enter SolarLeaf"))
        layout.addWidget(QLineEdit("24d7eb516930"))
        layout.addWidget(QPushButton("Select", clicked=self.search_gateways))

        self.sl_dialog.setLayout(layout)
        self.sl_dialog.exec_()

    def user_input_find(self):
        mac = self.sl_dialog.findChild(QLineEdit).text()
        if len(mac) != 12:
            print("MAC Address Length Not Correct")
            return

        # Continue Because Input is Valid
        self.sl_dialog.accept()

        return mac

    def search_gateways(self):
        mac_to_find = self.user_input_find()
        print(f"Looking for mac: {mac_to_find}")

        for gateway, broker in self.brokers.items():
            broker.publish("Yotta/cmd", "getid")

            time.sleep(5)
            while not broker.queue.empty():
                msg = broker.get()
                mac = msg_parts = msg.topic.split("/")[1]
                if mac == mac_to_find:
                    self.found_on_gateway = gateway
                    print(f"Found {mac_to_find} on {self.found_on_gateway}")
                    return self.found_on_gateway
                else:
                    print(f"{gateway} - {mac} does not match {mac_to_find}")

        print(f"{mac_to_find} not found on any gateway")

    def selected_unit(self):
        current_index = self.tabMenu.currentIndex()
        if current_index == -1:
            print("Add a tab and select a row to continue")
            return

        gateway = self.tabs[current_index]
        table = self.tables[gateway]

        selected = table.selectedItems()
        if not len(selected) > 0:
            print("No row selected.")
            return

        row = selected[0].row()
        cols = table.columnCount()
        items = [table.item(row, col).text() for col in range(cols)]

        print(f"Selected {items[1]} on row {row+1} on {items[0]}")
        return items

    def plot_fast(self):
        data = self.selected_unit()
        if not data:
            return

        gateway, mac = (data[0], data[1])
        broker = self.brokers[gateway]

        self.cmds.enable_fast(broker, mac)

        data_thread = self.threads[gateway]
        dialog = LineGraphDialog(data_thread)
        dialog.exec_()
        time.sleep(1)

        self.cmds.disable_fast(broker, mac)


class UpdateTableThread(QThread):
    slow_signal = pyqtSignal(str, list)
    plot_signal = pyqtSignal(str, list)
    stop = pyqtSignal()

    def __init__(self, broker, gateway, tabs):
        super().__init__()

        self.broker = broker
        self.gateway = gateway
        self.tabs = tabs

        self.Leaves: dict[str, SolarLEAF] = dict()

    def run(self):
        self.broker.publish(payload="getid")
        while True:
            data = self.broker.get()

            try:
                items = self.process(self.gateway, data)
            except Exception as err:
                print(f"UpdateTable Error: {err}")
            else:
                self.slow_signal.emit(self.gateway, items)
                self.plot_signal.emit(self.gateway, items)

            if self.gateway not in self.tabs.values():
                return

            time.sleep(0.1)

        print(f"Thread terminated for {self.gateway}")

    def set_value(self, leaf, data, name: str):
        if name in data.keys():
            setattr(leaf, name, data[name])

    def process(self, gateway, msg):
        if re.match("Yotta/............/", msg.topic):
            mac, topic = msg_parts = msg.topic.split("/")[1:3]

            # Associate SolarLeaf with Gateway
            index = len(self.Leaves) + 1
            leaf = self.Leaves.setdefault(mac, SolarLEAF(gateway, mac, index))

            if topic == "json":
                if "type" in (data := json.loads(msg.payload)):
                    [
                        self.set_value(leaf, data, name)
                        for name in config["list"]["names"]
                    ]
                    # print(data)

            return leaf.items()
            # return leaf.items()


class LineGraphDialog(QDialog):
    def __init__(self, thread, parent=None):
        super(LineGraphDialog, self).__init__(parent)

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

    def update_plot(self, gateway, new_data):
        # Append New Data
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
