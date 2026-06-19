import json
import os

_FILENAME = ".harvest_state.json"


def _path(directory: str) -> str:
    return os.path.join(directory, _FILENAME)


def read_last_run(directory: str) -> int | None:
    path = _path(directory)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    value = data.get("last_run_ms")
    return int(value) if value is not None else None


def write_last_run(directory: str, last_run_ms: int) -> None:
    os.makedirs(directory, exist_ok=True)
    with open(_path(directory), "w", encoding="utf-8") as fh:
        json.dump({"last_run_ms": int(last_run_ms)}, fh)
