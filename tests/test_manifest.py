import csv
import json
from autogis.core.models import AttachmentResult
from autogis.core.manifest import Manifest


def _sample():
    m = Manifest()
    m.add(AttachmentResult(1, 10, "a.jpg", "/out/G/a.jpg", 100, "downloaded"))
    m.add(AttachmentResult(2, 11, "b.jpg", None, None, "failed", "timeout"))
    return m


def test_write_csv(tmp_path):
    path = tmp_path / "manifest.csv"
    _sample().write_csv(str(path))
    rows = list(csv.DictReader(path.open()))
    assert rows[0]["objectid"] == "1"
    assert rows[0]["status"] == "downloaded"
    assert rows[1]["status"] == "failed"
    assert rows[1]["error"] == "timeout"


def test_write_json(tmp_path):
    path = tmp_path / "manifest.json"
    _sample().write_json(str(path))
    data = json.loads(path.read_text())
    assert len(data) == 2
    assert data[0]["attachment_id"] == 10
    assert data[1]["saved_path"] is None


def test_write_creates_both(tmp_path):
    out = tmp_path / "nested"
    csv_path, json_path = _sample().write(str(out))
    assert (out / "manifest.csv").exists()
    assert (out / "manifest.json").exists()
    assert csv_path.endswith("manifest.csv")
    assert json_path.endswith("manifest.json")
