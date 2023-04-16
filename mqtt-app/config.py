import toml
import argparse
from pathlib import Path


MQTT_CONFIG = Path("share/mqtt-app.toml")


class TomlReader(argparse.Action):
    def __init__(self, option_strings, dest, nargs=None, **kwargs):
        super().__init__(option_strings, dest, **kwargs)

    def __call__(self, parser, namespace, path, option_string=None):
        setattr(namespace, self.dest, toml.load(path))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "-c",
        "--config",
        help="override the default configuration file",
        default=toml.load(MQTT_CONFIG),
        action=TomlReader,
    )
    return p.parse_args()
