import re
import sys
import time
import json
import logging

from typing import Dict

from PyQt5.QtCore import pyqtSignal, QThread
from PyQt5.QtGui import QFont, QFontMetrics

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QComboBox,
    QLineEdit,
    QDialog,
    QWidget,
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.brokers = self._init_brokers()
        self.tabs: dict[int, str] = dict()
        self.tables: dict[int, QTableWidget] = dict()
        self.threads: dict[str, UpdateTableThread] = dict()

        self._initUI()
        self._init_menubar()

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

        # Create a tab widget
        self.tabMenu = QTabWidget()
        self.tabMenu.setTabsClosable(True)
        self.tabMenu.tabCloseRequested.connect(self.close_tab)
        self.setCentralWidget(self.tabMenu)

        # Set Geometry
        self.setGeometry(100, 100, 1800, 400)

    def _init_menubar(self):
        # Menubar
        menubar = self.menuBar()

        # File Menu
        menuAdd = QMenu("Add", self)
        tab_action = QAction("Gateway", self)
        tab_action.triggered.connect(self.add_gateway_dialog)
        menuAdd.addAction(tab_action)
        fileMenu = menubar.addMenu("File")
        fileMenu.addMenu(menuAdd)

        # TODO: Add Commands(class)
        # Command Menu
        findUnitAction = QAction("Find Unit", self)
        findUnitAction.triggered.connect(self.find_solarleaf_dialog)
        plotFastDataAction = QAction("Plot Fast", self)
        plotFastDataAction.triggered.connect(self.plot_fast)
        refreshAction = QAction("Current Tab", self)
        refreshAction.triggered.connect(self.current_tab)
        fileMenu = menubar.addMenu("Command")
        fileMenu.addAction(refreshAction)
        fileMenu.addAction(plotFastDataAction)
        fileMenu.addAction(findUnitAction)

    def add_gateway_dialog(self):
        self.gw_dialog = QDialog(self)
        self.gw_dialog.setWindowTitle("Gateway")
        self.gw_dialog.setGeometry(100, 200, 300, 100)

        combo_box = QComboBox()
        for gateway, broker in self.brokers.items():
            combo_box.addItem(gateway)

        label = QLabel("Select Gateway")
        button = QPushButton("Select")
        button.clicked.connect(lambda: self.add_tab(self.tabMenu.count()))

        layout = QVBoxLayout()
        layout.addWidget(label)
        layout.addWidget(combo_box)
        layout.addWidget(button)

        self.gw_dialog.setLayout(layout)

        self.gw_dialog.exec_()

    def find_solarleaf_dialog(self):
        self.sl_dialog = QDialog(self)
        self.sl_dialog.setWindowTitle("SolarLeaf")
        self.sl_dialog.setGeometry(100, 200, 300, 100)

        label = QLabel("Enter SolarLeaf")
        input_line = QLineEdit("aabbccddeeff")
        button = QPushButton("Select")
        button.clicked.connect(self.current_row)

        layout = QVBoxLayout()
        layout.addWidget(label)
        layout.addWidget(input_line)
        layout.addWidget(button)

        self.sl_dialog.setLayout(layout)

        self.sl_dialog.exec_()

    def add_tab(self, index):
        # Track Current Tab Based on Index
        self.gw_dialog.accept()
        gateway = self.gw_dialog.findChild(QComboBox).currentText()
        self.tabs[index] = gateway

        table = QTableWidget()
        self.tabMenu.addTab(table, gateway)
        self.tables[gateway] = table

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
        thread.signal.connect(self.add_item_to_table)
        thread.start()
        self.threads[gateway] = thread

        # Set New Tab as Current Tab
        self.tabMenu.setCurrentIndex(self.tabMenu.count() - 1)

    def add_item_to_table(self, gateway, item):
        # Add a new item to the table widget
        if gateway not in self.tabs.values():
            return

        table = self.tables[gateway]
        index = int(item[0]) - 1
        del item[0]

        # Implement New Entry
        row_count = table.rowCount()
        if index >= row_count:
            table.setRowCount(row_count + 1)

        # Update Entry Based on leaf.index
        for i, value in enumerate(item):
            currEntry = QTableWidgetItem(str(value))
            currEntry.setFont(FONT)
            table.setItem(index, i, currEntry)  # i-1 to not display index

        # Resize to Contents
        table.resizeRowsToContents()
        table.resizeColumnsToContents()
        for row in range(table.rowCount()):
            height = table.rowHeight(row)
            table.setRowHeight(row, height)

    def close_tab(self, index):
        # Get the widget of the closed tab
        widget_to_remove = self.tabMenu.widget(index)
        self.tabMenu.removeTab(index)
        widget_to_remove.deleteLater()

        thread = self.threads[self.tabs[index]]
        if thread.isFinished:
            thread.quit()

        del self.tabs[index]

    def current_tab(self, tab_index):
        current_index = self.tabMenu.currentIndex()
        try:
            print(current_index, self.tabs[tab_index])
        except:
            pass
        return current_index == tab_index

    def current_row(self):
        mac = self.sl_dialog.findChild(QLineEdit).text()
        if len(mac) != 12:
            print("MAC Address Length Not Correct")
            return
        elif len(mac) == 0:
            print("Enter a MAC Address")
            return

        # Valid Input - Continue
        self.sl_dialog.accept()
        print(mac)

    def find_selected_unit(self):
        current_index = self.tabMenu.currentIndex()
        if current_index == -1:
            return

        gateway = self.tabs[current_index]
        table = self.tables[gateway]

        selected = table.selectedItems()
        if len(selected) > 0:
            row = selected[0].row()
            print("Selected row:", row + 1)

            items = [
                table.item(row, column).text()
                for column in range(table.columnCount())
            ]

            print(items)
        else:
            print("No row selected.")

        return items

    def plot_fast(self):
        data = self.find_selected_unit()
        gateway, mac = (data[0], data[1])
        broker = self.brokers[gateway]
        broker.publish(
            f"Yotta/'{mac}'/cmd", payload="fast 1"
        )  # "fast_period 1")


class UpdateTableThread(QThread):
    signal = pyqtSignal(str, list)
    stop = pyqtSignal()

    def __init__(self, broker, gateway, tabs):
        super().__init__()

        self.broker = broker
        self.gateway = gateway
        self.tabs = tabs

        self.Leaves: dict[str, SolarLEAF] = dict()

    def run(self):
        self.broker.publish(cmd="getid")  # For Testing Remove Upon Completion
        while True:
            # while not self.broker.queue.empty():
            data = self.broker.queue.get()
            self.signal.emit(self.gateway, self.process(self.gateway, data))

            if self.gateway not in self.tabs.values():
                break

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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
