"""Round-trip tests for the dataclass<->CSV serialization home."""
import dataclasses
from datetime import date
from typing import Optional

import pytest

from autogis.core.common.records_csv import read_records_csv, write_records_csv


@dataclasses.dataclass
class _Rec:
    name: str
    count: int
    amount: Optional[float]
    when: Optional[date]


def test_round_trip_preserves_values(tmp_path):
    rows = [
        _Rec("a", 3, 5.5, date(2026, 4, 15)),
        _Rec("b", 0, None, None),
    ]
    out = tmp_path / "r.csv"
    write_records_csv(rows, out)
    back = read_records_csv(out, _Rec)
    assert back == rows


def test_optional_date_writes_iso_and_none_blank(tmp_path):
    out = tmp_path / "r.csv"
    write_records_csv([_Rec("a", 1, None, date(2026, 1, 2))], out)
    text = out.read_text(encoding="utf-8")
    assert "2026-01-02" in text          # date -> ISO
    lines = text.splitlines()
    # None amount serializes to an empty field (",,")
    assert lines[1].split(",")[2] == ""   # amount column blank


def test_empty_with_record_class_writes_header_only(tmp_path):
    out = tmp_path / "r.csv"
    write_records_csv([], out, record_class=_Rec)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines == ["name,count,amount,when"]


def test_header_matches_dataclass_field_order(tmp_path):
    out = tmp_path / "r.csv"
    write_records_csv([_Rec("a", 1, 2.0, None)], out)
    header = out.read_text(encoding="utf-8").splitlines()[0]
    assert header == "name,count,amount,when"


@dataclasses.dataclass
class _PEP604Rec:
    name: str
    amount: float | None
    when: date | None


def test_pep604_optional_fields_round_trip(tmp_path):
    """`X | None` field annotations coerce like Optional[X]."""
    rows = [_PEP604Rec("a", 1.5, date(2026, 4, 1)), _PEP604Rec("b", None, None)]
    out = tmp_path / "r.csv"
    write_records_csv(rows, out)
    back = read_records_csv(out, _PEP604Rec)
    assert back == rows


def test_record_class_inferred_from_first_record(tmp_path):
    out = tmp_path / "r.csv"
    write_records_csv([_Rec("a", 1, 2.0, date(2026, 1, 1))], out)  # no record_class
    back = read_records_csv(out, _Rec)
    assert back[0].name == "a"
