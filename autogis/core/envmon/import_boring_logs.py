"""import_boring_logs.py — parse boring-log CSV package → boring GDB tables (8.0b).

The parse + validate layer is arcpy-free and fully unit-testable. It produces
the canonical ``schema.boring`` dataclasses (BoringLocation, LithologyInterval,
BoringSample) directly — no parallel record types. ``import_boring_package`` is
LOCAL (arcpy), marked ``# pragma: no cover``; its GDB column names follow
``gdb_schema.py`` TABLE_SCHEMAS.

Input: a directory with ``boring_locations.csv``, ``lithology.csv`` and
``samples.csv`` (field-log multi-sheet export). CSV depth/elevation headers
carry an ``_ft`` suffix; the schema dataclass fields do not.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, SEV_ERROR, SEV_WARNING, SEV_INFO
from ..common.schema.boring import BoringLocation, LithologyInterval, BoringSample


def _s(row: dict, key: str) -> str:
    """None-safe cell read: csv.DictReader fills missing trailing columns with
    None, so coerce to str before stripping (a short row must not crash)."""
    return (row.get(key) or "").strip()


def _f(row: dict, key: str) -> Optional[float]:
    v = _s(row, key)
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_boring_locations_csv(path: Path) -> list[BoringLocation]:
    out: list[BoringLocation] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(BoringLocation(
                boring_id=_s(row, "BoringID"),
                site_id=_s(row, "SiteID"),
                location_type=_s(row, "LocationType"),
                northing=_f(row, "Northing"),
                easting=_f(row, "Easting"),
                ground_elevation=_f(row, "GroundElevation_ft"),
                toc_elevation=_f(row, "TOCElevation_ft"),
                status=_s(row, "Status"),
            ))
    return out


def parse_lithology_csv(
    path: Path, qa: Optional[QACollector] = None,
) -> list[LithologyInterval]:
    """Parse lithology rows. Rows lacking a numeric Top/BottomDepth_ft are
    dropped; if *qa* is supplied the drop is surfaced (never silent)."""
    out: list[LithologyInterval] = []
    dropped = 0
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            top = _f(row, "TopDepth_ft")
            bot = _f(row, "BottomDepth_ft")
            if top is None or bot is None:
                dropped += 1
                continue
            out.append(LithologyInterval(
                boring_id=_s(row, "BoringID"),
                top_depth=top, bottom_depth=bot,
                uscs=_s(row, "USCS"),
                primary_material=_s(row, "PrimaryMaterial"),
                color=_s(row, "Color"),
                moisture=_s(row, "Moisture"),
                description=_s(row, "Description"),
            ))
    if dropped and qa is not None:
        qa.add(SEV_WARNING, "lithology_rows_dropped_missing_depth",
               f"{dropped} lithology row(s) dropped: missing/invalid "
               f"TopDepth_ft or BottomDepth_ft")
    return out


def parse_boring_samples_csv(
    path: Path, qa: Optional[QACollector] = None,
) -> list[BoringSample]:
    """Parse sample rows. Rows lacking a numeric Top/BottomDepth_ft are dropped;
    if *qa* is supplied the drop is surfaced (never silent)."""
    out: list[BoringSample] = []
    dropped = 0
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            top = _f(row, "TopDepth_ft")
            bot = _f(row, "BottomDepth_ft")
            if top is None or bot is None:
                dropped += 1
                continue
            out.append(BoringSample(
                sample_id=_s(row, "SampleID"),
                boring_id=_s(row, "BoringID"),
                sample_type=_s(row, "SampleType"),
                top_depth=top, bottom_depth=bot,
                matrix=_s(row, "Matrix"),
            ))
    if dropped and qa is not None:
        qa.add(SEV_WARNING, "sample_rows_dropped_missing_depth",
               f"{dropped} sample row(s) dropped: missing/invalid "
               f"TopDepth_ft or BottomDepth_ft")
    return out


def load_boring_package(
    input_dir: Path, qa: Optional[QACollector] = None,
) -> tuple[list[BoringLocation], list[LithologyInterval], list[BoringSample]]:
    """Parse the three package CSVs from *input_dir*; missing files → empty lists.

    Pass *qa* so dropped rows (missing required depths) are surfaced as warnings.
    """
    d = Path(input_dir)
    locs = (parse_boring_locations_csv(d / "boring_locations.csv")
            if (d / "boring_locations.csv").exists() else [])
    intervals = (parse_lithology_csv(d / "lithology.csv", qa)
                 if (d / "lithology.csv").exists() else [])
    samples = (parse_boring_samples_csv(d / "samples.csv", qa)
               if (d / "samples.csv").exists() else [])
    return locs, intervals, samples


def validate_boring_package(
    locs: list[BoringLocation],
    intervals: list[LithologyInterval],
    samples: list[BoringSample],
    qa: QACollector,
) -> None:
    """Cross-check a parsed boring package, writing issues to *qa*."""
    known_boring_ids = {loc.boring_id for loc in locs}

    for iv in intervals:
        if iv.boring_id not in known_boring_ids:
            qa.add(SEV_WARNING, "lithology_boring_not_in_locations",
                   f"Lithology row references unknown boring {iv.boring_id!r}")
    for s in samples:
        if s.boring_id not in known_boring_ids:
            qa.add(SEV_WARNING, "sample_boring_not_in_locations",
                   f"Sample {s.sample_id!r} references unknown boring {s.boring_id!r}")

    by_boring: dict[str, list[LithologyInterval]] = defaultdict(list)
    for iv in intervals:
        by_boring[iv.boring_id].append(iv)
    for bid, ivs in by_boring.items():
        ordered = sorted(ivs, key=lambda x: x.top_depth)
        for a, b in zip(ordered, ordered[1:]):
            if a.bottom_depth > b.top_depth:
                qa.add(SEV_ERROR, "overlapping_intervals",
                       f"{bid}: interval {a.top_depth}-{a.bottom_depth} overlaps "
                       f"next interval starting at {b.top_depth}")

    qa.add(SEV_INFO, "validation_complete",
           f"Boring package: {len(locs)} locations, {len(intervals)} intervals, "
           f"{len(samples)} samples.")


def import_boring_package(  # pragma: no cover
    gdb_path: str,
    locs: list[BoringLocation],
    intervals: list[LithologyInterval],
    samples: list[BoringSample],
) -> None:
    """Write a parsed boring package to GDB tables (ArcGIS Pro)."""
    from pathlib import Path as _P

    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    gdb = str(gdb_path)

    loc_table = str(_P(gdb) / "BoringLocations")
    if _ax.Exists(loc_table):
        with _ax.da.InsertCursor(loc_table, [
            "BoringID", "SiteID", "LocationType", "Northing", "Easting",
            "GroundElevation_ft", "TOCElevation_ft", "Status",
        ]) as cur:
            for loc in locs:
                cur.insertRow([
                    loc.boring_id, loc.site_id, loc.location_type, loc.northing,
                    loc.easting, loc.ground_elevation, loc.toc_elevation,
                    loc.status,
                ])

    lith_table = str(_P(gdb) / "LithologyIntervals")
    if _ax.Exists(lith_table):
        with _ax.da.InsertCursor(lith_table, [
            "BoringID", "TopDepth_ft", "BottomDepth_ft", "USCS",
            "PrimaryMaterial", "Color", "Moisture", "Description",
        ]) as cur:
            for iv in intervals:
                cur.insertRow([
                    iv.boring_id, iv.top_depth, iv.bottom_depth, iv.uscs,
                    iv.primary_material, iv.color, iv.moisture, iv.description,
                ])

    samp_table = str(_P(gdb) / "BoringSamples")
    if _ax.Exists(samp_table):
        with _ax.da.InsertCursor(samp_table, [
            "SampleID", "BoringID", "SampleType", "TopDepth_ft",
            "BottomDepth_ft", "Matrix",
        ]) as cur:
            for s in samples:
                cur.insertRow([
                    s.sample_id, s.boring_id, s.sample_type, s.top_depth,
                    s.bottom_depth, s.matrix,
                ])
