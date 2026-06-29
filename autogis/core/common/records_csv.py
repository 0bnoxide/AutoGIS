"""Dataclass <-> CSV serialization — the single home for record I/O.

`read_records_csv` loads a CSV into a list of dataclass instances; `write_records_csv`
writes a list of dataclass instances to a CSV. The two round-trip: a value written
here reads back to the same Python value (``date`` -> ISO -> ``date``; Optional
``None`` -> empty field -> ``None``; non-Optional ``str`` blank -> ``""``;
``int`` empty -> ``0``).

No arcpy dependency.
"""
from __future__ import annotations

import csv
import dataclasses as _dc
import types
import typing
from datetime import date as _date
from pathlib import Path
from typing import List, Optional, Sequence, Type, TypeVar

T = TypeVar("T")


def _split_hint(hint):
    """Return ``(inner_type, is_optional)`` for a possibly-Optional hint.

    For ``Optional[X]`` / ``X | None`` returns ``(X, True)``; for a plain
    ``X`` returns ``(X, False)``. Recognizes both ``typing.Optional``/``Union``
    and PEP 604 ``X | None``.
    """
    origin = typing.get_origin(hint)
    if origin is typing.Union or origin is getattr(types, "UnionType", ()):
        args = typing.get_args(hint)
        non_none = [a for a in args if a is not type(None)]
        return (non_none[0] if non_none else str), (type(None) in args)
    return hint, False


def _coerce(value: str, hint):
    """Coerce a CSV string to the field's resolved type hint.

    A blank field deserializes to ``None`` only for Optional fields; for a
    non-Optional ``str`` it stays ``""`` (and a literal ``"None"`` string is
    preserved as-is) so the round-trip honors the field's annotation.
    """
    inner, optional = _split_hint(hint)
    # str fields carry their text verbatim: only a truly-empty field is special-
    # cased (to None when Optional, else ""). The literal "None" is a valid value.
    if inner is str:
        if value == "":
            return None if optional else ""
        return value
    if value in ("", "None"):
        if optional:
            return None
        if inner is int:
            return 0
        if inner is float:
            return 0.0
        return None
    if inner is int:
        try:
            return int(float(value))   # handles "0.0" written by asdict
        except (ValueError, TypeError):
            return 0
    if inner is float:
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    if inner is _date:
        try:
            return _date.fromisoformat(value)
        except (ValueError, TypeError):
            return None
    return value


def read_records_csv(path: Path, record_class: Type[T]) -> List[T]:
    """Load a CSV into a list of dataclass instances.

    Uses typing.get_type_hints() to resolve annotations (handles
    ``from __future__ import annotations``).  Unknown columns are ignored.
    ClassVar fields (e.g. table_name on schema dataclasses) are excluded
    so they are not passed to __init__.
    """
    _instance_fields = {f.name for f in _dc.fields(record_class)}
    hints = {k: v for k, v in typing.get_type_hints(record_class).items()
             if k in _instance_fields}
    rows = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            kwargs = {}
            for fname, hint in hints.items():
                raw = row.get(fname, "")
                try:
                    kwargs[fname] = _coerce(raw, hint)
                except (ValueError, TypeError):
                    kwargs[fname] = None
            rows.append(record_class(**kwargs))
    return rows


def write_records_csv(
    records: Sequence,
    path: Path,
    *,
    record_class: Optional[type] = None,
) -> Path:
    """Write a list of dataclass instances to a CSV.

    Column order follows the dataclass field order (ClassVar fields excluded by
    ``dataclasses.fields``). ``record_class`` is required only when ``records`` is
    empty; otherwise it is inferred from the first record. Round-trips with
    ``read_records_csv``.
    """
    cls = record_class or (type(records[0]) if records else None)
    if cls is None:
        raise ValueError(
            "write_records_csv: pass record_class when records is empty.")
    cols = [f.name for f in _dc.fields(cls)]
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for rec in records:
            writer.writerow(_dc.asdict(rec))
    return out
