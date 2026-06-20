import csv
import json
import os
import threading
from dataclasses import asdict, fields
from .models import AttachmentResult

_FIELDS = [f.name for f in fields(AttachmentResult)]


class Manifest:
    def __init__(self):
        self.results: list[AttachmentResult] = []
        # Lock the whole shared-state surface: add AND the iterating writers
        # (iterate-while-append race under parallel downloads). deltas C6.
        self._lock = threading.Lock()

    def add(self, result: AttachmentResult) -> None:
        with self._lock:
            self.results.append(result)

    def write_csv(self, path: str) -> None:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_FIELDS)
            writer.writeheader()
            with self._lock:
                rows = [asdict(r) for r in self.results]
            for row in rows:
                writer.writerow(row)

    def write_json(self, path: str) -> None:
        # Per-record JSON dump (deltas C7): keep this; envmon's
        # write_json_summary is an aggregate, not a replacement.
        with self._lock:
            data = [asdict(r) for r in self.results]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    def write(self, directory: str) -> tuple[str, str]:
        os.makedirs(directory, exist_ok=True)
        csv_path = os.path.join(directory, "manifest.csv")
        json_path = os.path.join(directory, "manifest.json")
        self.write_csv(csv_path)
        self.write_json(json_path)
        return csv_path, json_path
