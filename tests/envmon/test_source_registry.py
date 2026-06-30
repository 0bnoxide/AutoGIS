"""Tests for autogis/core/envmon/source_registry.py."""
from pathlib import Path

from autogis.core.envmon.source_registry import (
    SourceDocRecord,
    SourceRegistry,
    compute_sha256,
)


def _make_record(**kw) -> SourceDocRecord:
    defaults = dict(
        registered_at="2026-06-28T10:00:00",
        file_path="/data/H281/Q2-2026-lab.xlsx",
        sha256="a" * 64,
        file_size_bytes=20480,
        site_id="H281",
        event_id="2026-Q2",
        tool="import-edd",
        notes="",
    )
    defaults.update(kw)
    return SourceDocRecord(**defaults)


def test_register_and_list_two_records(tmp_path):
    reg = SourceRegistry(tmp_path / "source_docs.csv")
    reg.register(_make_record(file_path="/data/a.xlsx", sha256="a" * 64))
    reg.register(_make_record(file_path="/data/b.xlsx", sha256="b" * 64))
    records = reg.list_records()
    assert len(records) == 2
    paths = {r.file_path for r in records}
    assert paths == {"/data/a.xlsx", "/data/b.xlsx"}


def test_is_registered_true_after_register(tmp_path):
    reg = SourceRegistry(tmp_path / "source_docs.csv")
    sha = "c" * 64
    reg.register(_make_record(file_path="/data/c.xlsx", sha256=sha))
    assert reg.is_registered("/data/c.xlsx", sha) is True


def test_is_registered_false_before_register(tmp_path):
    reg = SourceRegistry(tmp_path / "source_docs.csv")
    assert reg.is_registered("/data/never.xlsx", "d" * 64) is False


def test_is_registered_false_on_hash_mismatch(tmp_path):
    reg = SourceRegistry(tmp_path / "source_docs.csv")
    reg.register(_make_record(file_path="/data/c.xlsx", sha256="c" * 64))
    # Same path, different hash → not registered (content changed).
    assert reg.is_registered("/data/c.xlsx", "e" * 64) is False


def test_filter_by_site_id(tmp_path):
    reg = SourceRegistry(tmp_path / "source_docs.csv")
    reg.register(_make_record(site_id="H281", sha256="e" * 64))
    reg.register(_make_record(site_id="LMFW", sha256="f" * 64))
    h281_records = reg.list_records(site_id="H281")
    assert len(h281_records) == 1
    assert h281_records[0].site_id == "H281"


def test_filter_by_event_id(tmp_path):
    reg = SourceRegistry(tmp_path / "source_docs.csv")
    reg.register(_make_record(event_id="2026-Q1", sha256="1" * 64))
    reg.register(_make_record(event_id="2026-Q2", sha256="2" * 64))
    q1 = reg.list_records(event_id="2026-Q1")
    assert len(q1) == 1
    assert q1[0].event_id == "2026-Q1"


def test_compute_sha256_consistent(tmp_path):
    f = tmp_path / "sample.txt"
    f.write_bytes(b"hello autogis")
    h1 = compute_sha256(f)
    h2 = compute_sha256(f)
    assert h1 == h2
    assert len(h1) == 64


def test_csv_header_written_once(tmp_path):
    csv_path = tmp_path / "source_docs.csv"
    reg = SourceRegistry(csv_path)
    reg.register(_make_record(sha256="h" * 64))
    reg.register(_make_record(sha256="i" * 64))
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("registered_at")
    header_count = sum(1 for ln in lines if ln.startswith("registered_at"))
    assert header_count == 1


def test_list_records_empty_file(tmp_path):
    reg = SourceRegistry(tmp_path / "source_docs.csv")
    assert reg.list_records() == []


def test_file_size_roundtrips_as_int(tmp_path):
    reg = SourceRegistry(tmp_path / "source_docs.csv")
    reg.register(_make_record(file_size_bytes=12345, sha256="j" * 64))
    rec = reg.list_records()[0]
    assert rec.file_size_bytes == 12345
    assert isinstance(rec.file_size_bytes, int)
