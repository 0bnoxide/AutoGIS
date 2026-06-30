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


@dataclasses.dataclass
class _StrRec:
    required: str
    optional: Optional[str]


def test_blank_non_optional_str_round_trips_to_empty_string(tmp_path):
    """A legitimately-blank non-Optional str must read back as "", not None."""
    rows = [_StrRec("", None), _StrRec("x", "kept")]
    out = tmp_path / "s.csv"
    write_records_csv(rows, out)
    back = read_records_csv(out, _StrRec)
    assert back[0].required == ""        # non-Optional blank -> ""
    assert back[0].optional is None      # Optional blank -> None
    assert back[1].required == "x"
    assert back[1].optional == "kept"


def test_literal_none_string_preserved_for_str_field(tmp_path):
    """The literal text "None" is a valid str value, not a null sentinel."""
    out = tmp_path / "s.csv"
    write_records_csv([_StrRec("None", "None")], out)
    back = read_records_csv(out, _StrRec)
    assert back[0].required == "None"
    assert back[0].optional == "None"


def test_record_class_inferred_from_first_record(tmp_path):
    out = tmp_path / "r.csv"
    write_records_csv([_Rec("a", 1, 2.0, date(2026, 1, 1))], out)  # no record_class
    back = read_records_csv(out, _Rec)
    assert back[0].name == "a"


@dataclasses.dataclass
class _BoolRec:
    name: str
    flag: bool
    maybe: Optional[bool]


def test_bool_fields_round_trip(tmp_path):
    """bool must read back as a real bool, not the string "True"/"False" (#73)."""
    rows = [
        _BoolRec("a", True, True),
        _BoolRec("b", False, False),
        _BoolRec("c", True, None),
    ]
    out = tmp_path / "b.csv"
    write_records_csv(rows, out)
    back = read_records_csv(out, _BoolRec)
    assert back == rows
    assert back[1].flag is False  # a written False must read back as bool False


def test_blank_bool_is_none_when_optional_else_false(tmp_path):
    """Blank field -> None for Optional[bool], False for a required bool (#73)."""
    out = tmp_path / "b.csv"
    out.write_text("name,flag,maybe\nx,,\n", encoding="utf-8")
    back = read_records_csv(out, _BoolRec)
    assert back[0].flag is False      # required blank -> False
    assert back[0].maybe is None      # Optional blank -> None
