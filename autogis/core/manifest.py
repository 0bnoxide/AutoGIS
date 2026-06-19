import csv
import json
import os
from dataclasses import asdict, fields
from .models import AttachmentResult

_FIELDS = [f.name for f in fields(AttachmentResult)]


class Manifest:
    def __init__(self):
        self.results: list[AttachmentResult] = []

    def add(self, result: AttachmentResult) -> None:
        self.results.append(result)

    def write_csv(self, path: str) -> None:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_FIELDS)
            writer.writeheader()
            for r in self.results:
                writer.writerow(asdict(r))

    def write_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([asdict(r) for r in self.results], fh, indent=2)

    def write(self, directory: str) -> tuple[str, str]:
        os.makedirs(directory, exist_ok=True)
        csv_path = os.path.join(directory, "manifest.csv")
        json_path = os.path.join(directory, "manifest.json")
        self.write_csv(csv_path)
        self.write_json(json_path)
        return csv_path, json_path
