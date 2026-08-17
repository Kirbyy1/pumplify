import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class RunLogger:
    def __init__(self, run_log_dir: Path):
        run_log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        self.path = run_log_dir / f"{stamp}.jsonl"
        self._lock = threading.Lock()

    def event(self, event_type: str, **fields: Any) -> None:
        record = {
            "time": datetime.now(UTC).isoformat(),
            "event": event_type,
            **fields,
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, sort_keys=True))
                f.write("\n")
