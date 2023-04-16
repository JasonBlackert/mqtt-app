import re
import sys
import time
import json

from PyQt5.QtCore import pyqtSignal, QThread
from PyQt5.QtGui import QFont, QFontMetrics

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QComboBox,
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

TIMEOUT = 65

FONT_SIZE = 8
FONT = QFont("Courier")
FONT.setPointSize(FONT_SIZE)

HEADER = config["list"]["header"]
NAMES = config["list"]["names"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self._initUI()
        self._init_menubar()

        self.pop_up()

    def _initUI(self):
        # Set Title
        self.setWindowTitle("On the Wall")

        # Create a tab widget
        self.tab_menu = QTabWidget()
        self.tab_menu.setTabsClosable(True)
        self.tab_menu.tabCloseRequested.connect(self.close_tab)
        self.setCentralWidget(self.tab_menu)

        # Layout
        layout = QHBoxLayout()
        layout.addWidget(self.tab_menu)

        # Create a central widget and set the layout
        central_widget = QWidget()
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

        # Set Geometry
        self.setGeometry(100, 100, 1800, 400)

    def _init_menubar(self):
        # Menubar
        menubar = self.menuBar()

        # File Menu
        menuAdd = QMenu("Add", self)
        tab_action = QAction("Gateway", self)
        tab_action.triggered.connect(self.pop_up)
        menuAdd.addAction(tab_action)
        fileMenu = menubar.addMenu("File")
        fileMenu.addMenu(menuAdd)

        # TODO: Add Commands(class)
        # Command Menu
        refreshAction = QAction("Current Tab", self)
        refreshAction.triggered.connect(self.current_tab)
        fileMenu = menubar.addMenu("Command")
        fileMenu.addAction(refreshAction)

    def pop_up(self):
        self.dialog = QDialog(self)
        self.dialog.setWindowTitle("Gateway")
        self.dialog.setGeometry(100, 200, 300, 100)

        combo_box = QComboBox()
        for gw in config["gateways"]:
            combo_box.addItem(gw)

        label = QLabel("Select Gateway")
        button = QPushButton("Select")
        button.clicked.connect(self.add_tab)

        layout = QVBoxLayout()
        layout.addWidget(label)
        layout.addWidget(combo_box)
        layout.addWidget(button)

        self.dialog.setLayout(layout)

        self.dialog.exec_()

    def add_tab(self):
        self.tab = Tab(self, self.tab_menu)

    def close_tab(self, index):
        # Get the widget of the closed tab
        widget_to_remove = self.tab_menu.widget(index)
        self.tab_menu.removeTab(index)
        widget_to_remove.deleteLater()

        self.tab.close(index)

    def current_tab(self, tab_index):
        current_index = self.tab_menu.currentIndex()
        print(current_index)
        return current_index == tab_index


class Tab:
    def __init__(self, MainWindow, tab_menu):
        self.mw = MainWindow
        self.tab_menu = tab_menu

        Leaves = {}

        self.tab = QWidget()
        self.table = QTableWidget()
        self.table.setColumnCount(len(HEADER))
        self.table.setHorizontalHeaderLabels(HEADER)
        style = "background-color: rgb(200, 200, 200); border: none;"
        self.table.setStyleSheet(f"QHeaderView::section { {style}}")

        # Table Style
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)

        self.table.horizontalHeader().setFont(FONT)
        font = self.table.horizontalHeader().font()
        font.setBold(True)
        self.table.horizontalHeader().setFont(font)

        # Add Table to Tab Layout
        tab_layout = QVBoxLayout()
        tab_layout.addWidget(self.table)
        self.tab.setLayout(tab_layout)

        # Find Current Gateway
        gateway = self.mw.sender().parent().findChild(QComboBox).currentText()
        self.mw.dialog.accept()

        self.tab_menu.addTab(self.tab, gateway)

        # Initialize Specific Broker
        self.broker = MQTT_Broker(config["gateways"][f"{gateway}"])
        self.broker.start()

        self.thread = UpdateTableThread(
            self.table, self.broker, gateway, Leaves
        )
        self.thread.new_item.connect(self.add_item_to_table)
        self.thread.start()

        # Set New Tab as Current Tab
        self.tab_menu.setCurrentIndex(self.tab_menu.count() - 1)

    def add_item_to_table(self, table, item):
        # Add a new item to the table widget

        # currTable = self.tab_menu.currentWidget().layout().itemAt(0).widget()
        index = int(item[0]) - 1

        # Implement New Entry
        row_count = table.rowCount()
        if index >= row_count:
            table.setRowCount(row_count + 1)

        # Update Entry Based on leaf.index
        for i, value in enumerate(item):
            currEntry = QTableWidgetItem(str(value))
            currEntry.setFont(FONT)
            table.setItem(index, i, currEntry)

        # Resize to Contents
        table.resizeRowsToContents()
        table.resizeColumnsToContents()

        # set maximum row height to readjusted size
        for row in range(table.rowCount()):
            height = table.rowHeight(row)
            table.setRowHeight(row, height)

    def close(self, gateway_host):
        if self.thread.isFinished:
            self.thread.quit()
        self.broker.stop(gateway_host)


class UpdateTableThread(QThread):
    new_item = pyqtSignal(QTableWidget, list)

    def __init__(self, table, broker, gateway, Leaves):
        super().__init__()

        self.table = table
        self.broker = broker
        self.gateway = gateway
        self.Leaves = Leaves

        self.previous = ""

    def run(self):
        # self.broker.publish(cmd="getid")  # For Testing Remove Upon Completion
        while True:
            while not self.broker.queue.empty():
                data = self.broker.queue.get()
                self.new_item.emit(
                    self.table,
                    self.process_leaf(self.gateway, data),
                )

            time.sleep(0.1)

    def set_value(self, leaf, data, name: str):
        if name in data.keys():
            setattr(leaf, name, data[name])

    def process_leaf(self, gateway, msg):
        if re.match("Yotta/............/", msg.topic):
            mac, topic = msg_parts = msg.topic.split("/")[1:3]

            # Associate SolarLeaf with Gateway
            index = len(self.Leaves) + 1
            leaf = self.Leaves.setdefault(mac, SolarLEAF(gateway, mac, index))

            if topic == "json":
                if "type" in (data := json.loads(msg.payload)):
                    [self.set_value(leaf, data, name) for name in NAMES]
                    print(data)

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
