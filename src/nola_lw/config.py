from pathlib import Path

import yaml


def load_config(path: Path = Path("config.yaml")) -> dict:
    return yaml.safe_load(Path(path).read_text())
