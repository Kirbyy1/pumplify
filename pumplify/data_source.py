import json
from pathlib import Path

from .log import log


def load_data_entries(file_path: str | Path) -> list[dict]:
    path = Path(file_path)

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            log(f"Warning: {path} does not contain a list. Using empty list.")
            return []
        return [entry for entry in data if isinstance(entry, dict)]
    except FileNotFoundError:
        log(f"Warning: {path} not found. Proceeding without overrides.")
        return []
    except json.JSONDecodeError:
        log(f"Warning: {path} is not valid JSON. Proceeding without overrides.")
        return []
