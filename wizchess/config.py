import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def load(path=CONFIG_PATH):
    with open(path) as f:
        return json.load(f)


def save(config, path=CONFIG_PATH):
    with open(path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
