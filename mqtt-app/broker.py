import re
import logging
import socket
import paho.mqtt.client as mqtt

from queue import Queue

from config import parse_args

args = parse_args()
config = args.config

lvl = "INFO"
log = logging.getLogger(__name__)
logging.basicConfig(level=lvl, format="%(name)s [%(levelname)s]: %(message)s")


class MQTT_Broker:
    def __init__(self, host):
        self.host = host
        self.client = mqtt.Client()

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

        self.queue = Queue()
        self.available = True

    def on_connect(self, client, userdata, flags, rc):
        log.info(f"Broker: {self.host} connected with result code {str(rc)}")
        client.subscribe("Yotta/#")

    def on_disconnect(self, client, userdata, rc):
        log.info(f"Broker: {self.host} disconnected with result code {str(rc)}")

    def on_message(self, client, userdata, msg):
        if re.match("Yotta/............/", msg.topic) is not None:
            self.queue.put(msg)

    def start(self):
        sock = socket.create_connection((self.host, 1883), timeout=2)
        self.client.socket = sock
        self.client.connect(self.host)
        self.client.loop_start()

    def stop(self, name):
        self.client.disconnect(name)
        self.client.loop_stop()

    def publish(self, topic: str = "Yotta/cmd", payload: str = "getid"):
        self.client.publish(topic, payload)

    def get(self):
        if self.available:
            self.available = False
            msg = self.queue.get()
            self.available = True

        return msg
