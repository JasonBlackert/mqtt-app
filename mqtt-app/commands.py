class Commands:
    def __init__(self, broker):
        self.broker = broker

    def find_unit(self):
        mac = "aabbccddeeff"
        print(mac)

    def enable_fast(self, mac):
        self.broker.publish("Yotta/cmd", payload="fast 1")

    def plot_fast(self):
        print("Fast")