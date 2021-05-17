from pathlib import Path
import yaml


def parse_secrets(file_path):
    file = Path(file_path)
    with open(file) as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            print("Error while parsing secrets file:")
            print(exc)
            return None
    return data
