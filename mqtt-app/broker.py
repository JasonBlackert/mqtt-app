import re
import logging
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
        # super.__init__()
        self.host = host
        self.client = mqtt.Client()

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

        self.queue = Queue()

    def on_connect(self, client, userdata, flags, rc):
        log.info(f"Broker: {self.host} connected with result code {str(rc)}")
        client.subscribe("Yotta/#")

    def on_disconnect(self, client, userdata, rc):
        log.info(f'Broker: {self.host} disconnected with result code {str(rc)}')

    def on_message(self, client, userdata, msg):
        if re.match("Yotta/............/", msg.topic) is not None:
            self.queue.put(msg)

    def start(self):
        self.client.connect(self.host)
        self.client.loop_start()

    def stop(self, name):
        self.client.disconnect(name)
        self.client.loop_stop()

    def publish(self, cmd: str = "getid"):
        self.client.publish("Yotta/cmd", cmd)