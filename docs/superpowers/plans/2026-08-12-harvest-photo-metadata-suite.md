# Harvest Photo-Metadata Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read the EXIF metadata already inside harvested photos (GPS, compass heading, timestamp) plus the manifest join, and ship four headless outputs — photo-points CSV/GeoJSON, photo↔feature QA, photographic log (xlsx/html/docx), KMZ — while the harvester finally fills the reserved `geometry`/`checksum` manifest columns.

**Architecture:** One extraction core (`core/envmon/photo_metadata.py`, `PhotoRecord` + `load_photo_records`) feeds thin emitters (`photo_points.py` for CSV/GeoJSON/KMZ, `photo_log.py` for the log). QA evaluation lives beside the record model in `photo_metadata.py`. A small `core/harvest/harvester.py` change populates `geometry` (representative point, WGS84), `checksum`/`algorithm` (sha256), and a new `feature_edited_at` column. CLI is a new `autogis envmon photos` subgroup.

**Tech Stack:** stdlib (`csv`, `json`, `zipfile`, `hashlib`, `math`, `xml.etree` in tests), Pillow lazy-imported (existing `[report]` extra), openpyxl (already a core dep), `python-docx` behind a NEW `[report-docx]` extra. No arcpy, no arcgis anywhere in the new modules.

**Spec:** `docs/superpowers/specs/2026-08-12-harvest-photo-metadata-suite-design.md` (owner-approved).

## Global Constraints

- `core/` and `adapters/` MUST import with neither `arcpy` nor `arcgis` present; Pillow and python-docx are lazy-imported inside the functions that need them, never at module scope.
- Run tests from the repo root with `python -m pytest -q` (dev venv, arcpy-free). Image-dependent tests gate with `pytest.importorskip("PIL")`; docx tests with `pytest.importorskip("docx")`.
- Every consumer treats `geometry`, `checksum`, `algorithm`, `feature_edited_at` as optional (old manifests carry nulls / empty strings).
- Geometry stored as `{"lat": <dd>, "lon": <dd>}` JSON, WGS84 decimal degrees. Supported source wkids: 4326 pass-through, 3857/102100 converted closed-form. Anything else → geometry null + one `logging` warning per layer.
- QA thresholds: `--max-offset-m` default 100.0; date check is day-level with ±1 day tolerance.
- CLI: subgroup `autogis envmon photos` with commands `points`, `qa`, `log`, `kmz`; each headless command ends with the shared `_render_qa(qa, report, fail_on)` contract via the existing `qa_report_options` decorator.
- Commit after every task; branch `claude/harvest-photo-metadata-feature-ef68e6` (already the current worktree branch); `main` is READ-ONLY. Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Ponytail (full) governs implementation: reuse existing helpers (`load_manifest`, `prepare_image_bytes`, `report_html`, `qa_report_options`), no new abstractions beyond this plan.
- Found a bug in committed code while working → file a GitHub issue for it (check open+closed first), per CLAUDE.md.

---

### Task 1: EXIF extraction core (`PhotoRecord` + `load_photo_records`)

**Files:**
- Create: `autogis/core/envmon/photo_metadata.py`
- Modify (create if absent): `tests/envmon/conftest.py` — add the `make_photo_jpeg` factory fixture
- Test: `tests/envmon/test_photo_metadata.py`

**Interfaces:**
- Consumes: `autogis.core.envmon.index_field_attachments.load_manifest(path) -> list[dict]` (existing); `autogis.core.common.qa.QACollector` with `qa.add(SEV_WARNING, category, message)` (existing).
- Produces (later tasks rely on these exact names):
  - `@dataclass PhotoRecord` with fields `objectid: int | None`, `attachment_id: int | None`, `source_table: str | None`, `group: str`, `saved_path: str`, `exif_lat: float | None`, `exif_lon: float | None`, `heading_deg: float | None`, `heading_ref: str | None`, `taken_at: str | None`, `camera: str | None`, `feature_lat: float | None`, `feature_lon: float | None`, `feature_edited_at: str | None`, `offset_m: float | None`, `exif_error: str | None`
  - `load_photo_records(harvest_dir: Path, qa: QACollector) -> list[PhotoRecord]`
  - `extract_exif(path: Path) -> dict` (keys: `exif_lat`, `exif_lon`, `heading_deg`, `heading_ref`, `taken_at`, `camera`; missing values absent or None; raises `ImportError` with install hint when Pillow missing; returns `{"exif_error": "<msg>"}` for unreadable files)
  - `haversine_m(lat1, lon1, lat2, lon2) -> float`
  - `PILLOW_HINT` (str constant), `IMAGE_SUFFIXES` (frozenset of lowercase suffixes)

- [ ] **Step 1: Add the synthetic-EXIF photo factory fixture to `tests/envmon/conftest.py`**

If the file does not exist, create it with exactly this content; if it exists, append the fixture (keeping existing imports deduplicated):

```python
import pytest


@pytest.fixture
def make_photo_jpeg(tmp_path):
    """Factory: write a tiny JPEG with crafted EXIF; returns the Path.

    lat/lon are decimal degrees (sign -> N/S, E/W ref); heading in degrees
    true; dto is EXIF DateTimeOriginal ("YYYY:MM:DD HH:MM:SS"). Pass None to
    omit a block entirely.
    """
    pytest.importorskip("PIL")
    from PIL import Image

    def _dms(dd):
        dd = abs(dd)
        d = int(dd)
        m = int((dd - d) * 60)
        s = (dd - d - m / 60) * 3600
        return (float(d), float(m), round(s, 4))

    def _make(name="p.jpg", lat=45.874, lon=-103.487, heading=231.5,
              dto="2026:05:05 08:17:36", camera=("samsung", "SM-X308U"),
              directory=None):
        img = Image.new("RGB", (8, 6), "red")
        exif = Image.Exif()
        if camera:
            exif[271], exif[272] = camera  # Make, Model
        gps = {}
        if lat is not None and lon is not None:
            gps.update({1: "N" if lat >= 0 else "S", 2: _dms(lat),
                        3: "E" if lon >= 0 else "W", 4: _dms(lon)})
        if heading is not None:
            gps.update({16: "T", 17: float(heading)})
        if gps:
            exif[0x8825] = gps  # GPSInfo IFD
        if dto is not None:
            exif[0x8769] = {36867: dto}  # ExifIFD: DateTimeOriginal
        out_dir = directory or tmp_path
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / name
        img.save(p, format="JPEG", exif=exif)
        return p

    return _make
```

- [ ] **Step 2: Write the failing tests**

Create `tests/envmon/test_photo_metadata.py`:

```python
import json
from pathlib import Path

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.photo_metadata import (
    PhotoRecord, extract_exif, haversine_m, load_photo_records)


def _manifest(tmp_path, rows):
    (tmp_path / "manifest.json").write_text(
        json.dumps(rows), encoding="utf-8")


def _row(saved_path, **kw):
    base = {"objectid": 2, "attachment_id": 7, "original_name": "Photo 1.jpg",
            "saved_path": None if saved_path is None else str(saved_path),
            "size": 5, "status": "downloaded",
            "error": None, "disposition": "downloaded", "checksum": None,
            "algorithm": None, "geometry": None,
            "source_table": "Observation_Point", "relationship_id": None,
            "feature_edited_at": None}
    base.update(kw)
    return base


def test_extract_exif_round_trip(make_photo_jpeg):
    p = make_photo_jpeg(lat=45.874, lon=-103.487, heading=231.5)
    got = extract_exif(p)
    assert got["exif_lat"] == pytest.approx(45.874, abs=1e-4)
    assert got["exif_lon"] == pytest.approx(-103.487, abs=1e-4)
    assert got["heading_deg"] == pytest.approx(231.5)
    assert got["heading_ref"] == "T"
    assert got["taken_at"] == "2026-05-05T08:17:36"
    assert got["camera"] == "samsung SM-X308U"


def test_extract_exif_no_gps(make_photo_jpeg):
    p = make_photo_jpeg(lat=None, lon=None, heading=None)
    got = extract_exif(p)
    assert got.get("exif_lat") is None and got.get("exif_lon") is None
    assert got["taken_at"] == "2026-05-05T08:17:36"


def test_extract_exif_unreadable(tmp_path):
    pytest.importorskip("PIL")
    p = tmp_path / "bad.jpg"
    p.write_bytes(b"not a jpeg at all")
    got = extract_exif(p)
    assert "exif_error" in got


def test_haversine_known_distance():
    # 0.01 deg latitude ~ 1111.9 m
    assert haversine_m(45.0, -103.0, 45.01, -103.0) == pytest.approx(
        1111.95, rel=0.01)


def test_load_photo_records_joins_manifest_and_exif(tmp_path, make_photo_jpeg):
    p = make_photo_jpeg(name="Picnic_3_Photo_1.jpg",
                        directory=tmp_path / "Obs_1" / "SeepSpring")
    _manifest(tmp_path, [_row(
        p, geometry={"lat": 45.875, "lon": -103.487},
        feature_edited_at="2026-05-05T14:20:00+00:00")])
    qa = QACollector()
    recs = load_photo_records(tmp_path, qa)
    assert len(recs) == 1
    r = recs[0]
    assert r.objectid == 2 and r.source_table == "Observation_Point"
    assert r.group == "Obs_1/SeepSpring"
    assert r.exif_lat == pytest.approx(45.874, abs=1e-4)
    assert r.feature_lat == pytest.approx(45.875)
    assert r.feature_edited_at == "2026-05-05T14:20:00+00:00"
    assert r.offset_m == pytest.approx(
        haversine_m(r.exif_lat, r.exif_lon, 45.875, -103.487), rel=1e-6)


def test_load_photo_records_csv_manifest_with_string_nulls(
        tmp_path, make_photo_jpeg):
    # CSV DictReader yields "" for nulls and strings for numbers.
    p = make_photo_jpeg(directory=tmp_path / "G")
    import csv
    row = _row(p, geometry="", feature_edited_at="")
    row = {k: ("" if v is None else v) for k, v in row.items()}
    with (tmp_path / "manifest.csv").open("w", newline="",
                                          encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        w.writeheader()
        w.writerow(row)
    qa = QACollector()
    recs = load_photo_records(tmp_path, qa)
    assert len(recs) == 1
    assert recs[0].objectid == 2
    assert recs[0].feature_lat is None


def test_load_photo_records_skips_failed_and_missing(tmp_path, make_photo_jpeg):
    p = make_photo_jpeg(directory=tmp_path / "G")
    rows = [
        _row(p),
        _row(tmp_path / "G" / "gone.jpg"),           # file missing on disk
        _row(None, status="failed", disposition="failed"),
        _row(tmp_path / "G" / "doc.pdf"),            # non-image suffix
    ]
    (tmp_path / "G" / "doc.pdf").write_bytes(b"%PDF-1.4")
    _manifest(tmp_path, rows)
    qa = QACollector()
    recs = load_photo_records(tmp_path, qa)
    assert [Path(r.saved_path).name for r in recs] == ["p.jpg"]
    cats = {r.category for r in qa.records}
    assert "photo_missing" in cats and "non_image_attachment" in cats


def test_load_photo_records_no_manifest(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_photo_records(tmp_path, QACollector())
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_photo_metadata.py -q`
Expected: collection error / ImportError — `autogis.core.envmon.photo_metadata` does not exist.

- [ ] **Step 4: Implement `autogis/core/envmon/photo_metadata.py`**

```python
"""photo_metadata.py — EXIF extraction core for harvest photo tools.

Reads a harvest output directory (the attachment harvester's
``manifest.csv``/``.json`` plus the downloaded files) and produces
``PhotoRecord`` rows joining manifest identity (objectid, source_table,
group) with the EXIF the field device embedded: GPS position, compass
heading (``GPSImgDirection``), capture time, camera. Feature-side geometry
and edit date come from the manifest when the harvest was made by a version
that fills them; both are optional (older manifests carry nulls).

Pillow is lazy-imported inside ``extract_exif`` (install:
``pip install "autogis[report]"``). No arcpy. No arcgis.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional

from autogis.core.common.qa import QACollector, SEV_INFO, SEV_WARNING
from autogis.core.envmon.index_field_attachments import load_manifest

PILLOW_HINT = ("Pillow is required to read photo EXIF; install with: "
               "pip install \"autogis[report]\"")
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff"})
_USABLE_DISPOSITIONS = {"downloaded", "skipped"}


@dataclass
class PhotoRecord:
    objectid: int | None
    attachment_id: int | None
    source_table: str | None
    group: str
    saved_path: str
    exif_lat: float | None = None
    exif_lon: float | None = None
    heading_deg: float | None = None
    heading_ref: str | None = None
    taken_at: str | None = None            # naive local ISO8601 from EXIF
    camera: str | None = None
    feature_lat: float | None = None
    feature_lon: float | None = None
    feature_edited_at: str | None = None   # ISO8601 UTC from manifest
    offset_m: float | None = None          # haversine photo->feature
    exif_error: str | None = None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371008.8  # mean Earth radius
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def _dms_to_dd(dms, ref) -> Optional[float]:
    try:
        d, m, s = (float(v) for v in dms)
    except (TypeError, ValueError):
        return None
    dd = d + m / 60.0 + s / 3600.0
    return -dd if ref in ("S", "W") else dd


def extract_exif(path: Path) -> dict:
    """EXIF fields of one image file; ``{"exif_error": ...}`` if unreadable."""
    try:
        from PIL import ExifTags, Image
    except ImportError as exc:
        raise ImportError(PILLOW_HINT) from exc
    out: dict = {}
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
            sub = exif.get_ifd(ExifTags.IFD.Exif)
    except OSError as exc:  # UnidentifiedImageError subclasses OSError
        return {"exif_error": f"unreadable image: {exc}"}
    try:
        out["exif_lat"] = _dms_to_dd(gps.get(2), gps.get(1))
        out["exif_lon"] = _dms_to_dd(gps.get(4), gps.get(3))
        if gps.get(17) is not None:                 # GPSImgDirection
            out["heading_deg"] = float(gps[17])
            out["heading_ref"] = gps.get(16) or None
        dto = sub.get(36867) or exif.get(306)       # DateTimeOriginal|DateTime
        if dto:
            date, _, time = str(dto).partition(" ")
            out["taken_at"] = f"{date.replace(':', '-')}T{time}"
        make, model = exif.get(271), exif.get(272)
        if make or model:
            out["camera"] = " ".join(s for s in (str(make or "").strip(),
                                                 str(model or "").strip()) if s)
    except (TypeError, ValueError) as exc:
        out["exif_error"] = f"corrupt EXIF: {exc}"
    return out


def _int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _geom_latlon(v) -> tuple[Optional[float], Optional[float]]:
    if isinstance(v, str):
        v = json.loads(v) if v.strip() else None
    if not isinstance(v, dict):
        return None, None
    try:
        return float(v["lat"]), float(v["lon"])
    except (KeyError, TypeError, ValueError):
        return None, None


def _group_of(saved: str, harvest_dir: Path) -> str:
    parts = PurePosixPath(str(saved).replace("\\", "/"))
    try:
        rel = parts.relative_to(
            PurePosixPath(str(harvest_dir).replace("\\", "/")))
        return "/".join(rel.parts[:-1])
    except ValueError:
        return parts.parent.name


def load_photo_records(harvest_dir: Path, qa: QACollector) -> list[PhotoRecord]:
    """Manifest rows joined with per-file EXIF, one record per usable photo."""
    harvest_dir = Path(harvest_dir)
    manifest = next((harvest_dir / n for n in ("manifest.json", "manifest.csv")
                     if (harvest_dir / n).is_file()), None)
    if manifest is None:
        raise FileNotFoundError(
            f"no manifest.json/manifest.csv in {harvest_dir} — is this a "
            f"harvest output directory?")
    records: list[PhotoRecord] = []
    missing, non_image = [], []
    for row in load_manifest(manifest):
        disposition = row.get("disposition") or row.get("status")
        saved = row.get("saved_path")
        if disposition not in _USABLE_DISPOSITIONS or not saved:
            continue
        p = Path(str(saved).replace("\\", "/"))
        if not p.is_absolute():
            p = harvest_dir / p
        if p.suffix.lower() not in IMAGE_SUFFIXES:
            non_image.append(p.name)
            continue
        if not p.is_file():
            missing.append(p.name)
            continue
        flat, flon = _geom_latlon(row.get("geometry"))
        rec = PhotoRecord(
            objectid=_int(row.get("objectid")),
            attachment_id=_int(row.get("attachment_id")),
            source_table=row.get("source_table") or None,
            group=_group_of(str(p), harvest_dir),
            saved_path=str(p),
            feature_lat=flat, feature_lon=flon,
            feature_edited_at=row.get("feature_edited_at") or None,
            **extract_exif(p))
        if (rec.exif_lat is not None and rec.exif_lon is not None
                and flat is not None and flon is not None):
            rec.offset_m = haversine_m(rec.exif_lat, rec.exif_lon, flat, flon)
        records.append(rec)
    if missing:
        qa.add(SEV_WARNING, "photo_missing",
               f"{len(missing)} manifest photo(s) not found on disk: "
               f"{', '.join(sorted(missing)[:5])}")
    if non_image:
        qa.add(SEV_INFO, "non_image_attachment",
               f"{len(non_image)} non-image attachment(s) skipped: "
               f"{', '.join(sorted(non_image)[:5])}")
    return records
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_photo_metadata.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/photo_metadata.py tests/envmon/conftest.py tests/envmon/test_photo_metadata.py
git commit -m "feat(envmon): PhotoRecord EXIF extraction core over harvest manifests"
```

---

### Task 2: Harvester fills the reserved manifest columns

**Files:**
- Modify: `autogis/core/harvest/models.py` (append one field to `AttachmentResult`)
- Modify: `autogis/core/harvest/harvester.py` (`_harvest_layer` + private helpers)
- Test: `tests/test_harvester.py` (extend fakes + new tests; keep its existing legacy import style)

**Interfaces:**
- Consumes: existing `AttachmentResult`, `Manifest`, `download_one`, `_prop`.
- Produces: manifest rows where `geometry` = `'{"lat": .., "lon": ..}'` JSON string (WGS84) or None; `checksum` = sha256 hex / `algorithm` = `"sha256"` for rows whose file exists; `feature_edited_at` = ISO8601 UTC string or None. New dataclass field `AttachmentResult.feature_edited_at: str | None = None` (declared LAST so the CSV column appends after existing ones).

- [ ] **Step 1: Write the failing tests (append to `tests/test_harvester.py`)**

Extend the fakes minimally — add `geometry=None` to `FakeFeature.__init__` (stored as `self.geometry`) and `spatial_reference=None` to `FakeQueryResult.__init__` (stored as `self.spatial_reference`); existing constructor calls keep working. Then add:

```python
import hashlib
import json as _json
import math
from datetime import datetime, timezone


def test_harvest_fills_geometry_checksum_editdate(tmp_path):
    # Web Mercator x/y computed in-test with the FORWARD projection formula;
    # the harvester implements the INVERSE — a genuine round-trip, not a
    # mirror of the implementation.
    lat, lon = 45.874, -103.487
    r_earth = 6378137.0
    x = r_earth * math.radians(lon)
    y = r_earth * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    edit_ms = int(datetime(2026, 5, 5, 14, 37, 36,
                           tzinfo=timezone.utc).timestamp() * 1000)
    features = [FakeFeature(
        {"OBJECTID": 1, "Status": "Done", "EditDate": edit_ms},
        geometry={"x": x, "y": y,
                  "spatialReference": {"wkid": 102100, "latestWkid": 3857}})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    layer = FakeLayer(features, listing, props={
        "hasAttachments": True,
        "editFieldsInfo": {"editDateField": "EditDate"}})
    summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    r = summary.results[0]
    geom = _json.loads(r.geometry)
    assert geom["lat"] == pytest.approx(45.874, abs=1e-5)
    assert geom["lon"] == pytest.approx(-103.487, abs=1e-5)
    assert r.algorithm == "sha256"
    assert r.checksum == hashlib.sha256(b"x").hexdigest()
    assert r.feature_edited_at == "2026-05-05T14:37:36+00:00"
    # geometry survives the manifest round-trip as a JSON string
    rows = _json.loads((tmp_path / "manifest.json").read_text())
    assert _json.loads(rows[0]["geometry"])["lat"] == geom["lat"]


def test_harvest_geometry_wgs84_passthrough_and_centroid(tmp_path):
    features = [FakeFeature(
        {"OBJECTID": 1, "Status": "Done"},
        geometry={"rings": [[[10.0, 40.0], [12.0, 40.0], [12.0, 42.0],
                             [10.0, 42.0], [10.0, 40.0]]],
                  "spatialReference": {"wkid": 4326}})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    layer = FakeLayer(features, listing)
    summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    geom = _json.loads(summary.results[0].geometry)
    assert geom == {"lat": pytest.approx(40.8), "lon": pytest.approx(10.8)}


def test_harvest_unknown_wkid_leaves_geometry_null(tmp_path, caplog):
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"},
                            geometry={"x": 1.0, "y": 2.0,
                                      "spatialReference": {"wkid": 26913}})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    layer = FakeLayer(features, listing)
    with caplog.at_level("WARNING"):
        summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                    now_ms=1, sleep=lambda s: None)
    assert summary.results[0].geometry is None
    assert any("spatial reference" in m for m in caplog.messages)


def test_harvest_skipped_existing_file_still_hashed(tmp_path):
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    layer = FakeLayer(features, listing)
    target = tmp_path / "Done" / "1_a.jpg"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    r = summary.results[0]
    assert r.status == "skipped"
    assert r.checksum == hashlib.sha256(b"old").hexdigest()


def test_harvest_no_geometry_attr_stays_null(tmp_path):
    # Old-style feature (no .geometry): everything still works, columns null.
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    layer = FakeLayer(features, listing)
    summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    r = summary.results[0]
    assert r.geometry is None and r.feature_edited_at is None
```

Also update `FakeLayer.query` to accept and record the flag: `def query(self, where, out_fields, return_geometry): self.last_where = where; self.last_return_geometry = return_geometry; ...` and add one assertion to the existing `test_harvest_downloads_and_groups`: `assert layer.last_return_geometry is True`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_harvester.py -q`
Expected: new tests FAIL (`geometry` is None / no `feature_edited_at` / no checksum); existing tests still pass.

- [ ] **Step 3: Implement in `autogis/core/harvest/models.py`**

Append to `AttachmentResult` after `relationship_id` (comment included):

```python
    # ISO8601 UTC editor-tracking EditDate of the source feature, when the
    # layer has editFieldsInfo; enables photo-vs-feature date QA downstream.
    feature_edited_at: str | None = None
```

- [ ] **Step 4: Implement in `autogis/core/harvest/harvester.py`**

Add imports at top: `import hashlib`, `import json`, `import logging`, `import math`, `from datetime import datetime, timezone`; module logger `logger = logging.getLogger(__name__)`.

Add private helpers (above `_harvest_layer`):

```python
_WEB_MERCATOR_WKIDS = {3857, 102100}
_R = 6378137.0


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _vertices(geom):
    if geom.get("x") is not None and geom.get("y") is not None:
        return [(geom["x"], geom["y"])]
    parts = geom.get("paths") or geom.get("rings") or []
    return [(x, y) for part in parts for x, y, *_ in part]


def _rep_point_wgs84(geom, result):
    """Representative point of an Esri geometry dict as (lat, lon) WGS84.

    Returns None for absent/empty geometry (silent — normal for tables) or
    the sentinel string "unsupported" when geometry exists but its spatial
    reference is missing or not convertible (caller warns once per layer).
    ponytail: 4326 + web-mercator only; extend when another SR shows up.
    """
    if not isinstance(geom, dict):
        return None
    verts = _vertices(geom)
    if not verts:
        return None
    x = sum(v[0] for v in verts) / len(verts)
    y = sum(v[1] for v in verts) / len(verts)
    sr = geom.get("spatialReference") or getattr(
        result, "spatial_reference", None) or {}
    wkid = (sr.get("latestWkid") or sr.get("wkid")) if isinstance(sr, dict) \
        else None
    if wkid == 4326:
        return (y, x)
    if wkid in _WEB_MERCATOR_WKIDS:
        lon = math.degrees(x / _R)
        lat = math.degrees(2 * math.atan(math.exp(y / _R)) - math.pi / 2)
        return (lat, lon)
    return "unsupported"


def _edit_date_field(layer):
    info = _prop(layer.properties, "editFieldsInfo")
    return _prop(info, "editDateField") if info else None


def _iso_utc(ms):
    try:
        return datetime.fromtimestamp(
            int(ms) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None
```

Then rework `_harvest_layer`'s body: query with `return_geometry=True`; per feature compute `geometry_json` and `edited_at` once and pass them into all three `AttachmentResult(...)` constructions (`geometry=geometry_json, feature_edited_at=edited_at`); hash files for the skipped branch (`checksum=_sha256(dest), algorithm="sha256"`) and after a successful `download_one` (same kwargs); count unsupported-SR features and emit ONE `logger.warning` per layer after the loop:

```python
def _harvest_layer(layer, config, manifest, base_dir, source_table, sleep):
    """Query ONE layer/table and accumulate its attachments into the shared
    manifest, rooting destination paths at ``base_dir``."""
    where = _effective_where(config, layer)
    result = layer.query(where=where, out_fields="*", return_geometry=True)
    edit_field = _edit_date_field(layer)
    unsupported_sr = 0
    for feature in result.features:
        attrs = feature.attributes
        objectid = attrs.get("OBJECTID")
        rep = _rep_point_wgs84(getattr(feature, "geometry", None), result)
        if rep == "unsupported":
            unsupported_sr += 1
            rep = None
        geometry_json = (json.dumps(
            {"lat": round(rep[0], 7), "lon": round(rep[1], 7)})
            if rep else None)
        edited_at = _iso_utc(attrs.get(edit_field)) if edit_field else None
        for att in layer.attachments.get_list(oid=objectid):
            att_id, name, size = att["id"], att["name"], att.get("size")
            group = render_path_component(config.group_template, attrs)
            fname = render_path_component(
                config.filename_template, {**attrs, "name": name})
            dest = os.path.join(base_dir, group, fname)

            if config.skip_existing and os.path.exists(dest):
                manifest.add(AttachmentResult(
                    objectid, att_id, name, dest, size, "skipped",
                    disposition="skipped", source_table=source_table,
                    checksum=_sha256(dest), algorithm="sha256",
                    geometry=geometry_json, feature_edited_at=edited_at))
                continue
            try:
                download_one(layer, objectid, att_id, dest,
                             config.retries, config.backoff_seconds, sleep=sleep)
                manifest.add(AttachmentResult(
                    objectid, att_id, name, dest, size, "downloaded",
                    disposition="downloaded", source_table=source_table,
                    checksum=_sha256(dest), algorithm="sha256",
                    geometry=geometry_json, feature_edited_at=edited_at))
            except Exception as exc:  # resilience: never kill the run
                manifest.add(AttachmentResult(
                    objectid, att_id, name, None, size, "failed", str(exc),
                    disposition="failed", source_table=source_table,
                    geometry=geometry_json, feature_edited_at=edited_at))
    if unsupported_sr:
        logger.warning(
            "%s: %d feature(s) in an unsupported spatial reference — "
            "manifest geometry left null (supported: WGS84, Web Mercator)",
            source_table, unsupported_sr)
```

Note the sentinel: `_rep_point_wgs84` returns `None` (no geometry / no SR — silent, normal for tables) vs the string `"unsupported"` (has geometry+wkid but not convertible — warned). Keep that exact contract; the test for unknown wkid depends on the warning.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/test_harvester.py tests/envmon/test_photo_metadata.py -q` then `python -m pytest -q`
Expected: all PASS (manifest consumers read by name, so the appended column is inert elsewhere; if any test asserts exact manifest headers, update it to include `feature_edited_at`).

- [ ] **Step 6: Commit**

```bash
git add autogis/core/harvest/models.py autogis/core/harvest/harvester.py tests/test_harvester.py
git commit -m "feat(harvest): fill reserved geometry/checksum columns + feature_edited_at"
```

---

### Task 3: Photo↔feature QA evaluation

**Files:**
- Modify: `autogis/core/envmon/photo_metadata.py` (add `evaluate_photo_qa`)
- Test: `tests/envmon/test_photo_metadata.py` (append)

**Interfaces:**
- Consumes: `PhotoRecord`, `QACollector`, `SEV_INFO`, `SEV_WARNING`.
- Produces: `evaluate_photo_qa(records: list[PhotoRecord], qa: QACollector, *, max_offset_m: float = 100.0) -> dict` returning `{"n_photos", "checked_offset", "flagged_offset", "checked_date", "flagged_date", "missing_gps", "unreadable"}`.

- [ ] **Step 1: Write the failing tests (append to `tests/envmon/test_photo_metadata.py`)**

```python
from autogis.core.envmon.photo_metadata import evaluate_photo_qa


def _rec(**kw):
    base = dict(objectid=1, attachment_id=1, source_table="T", group="G",
                saved_path="G/p.jpg")
    base.update(kw)
    return PhotoRecord(**base)


def test_qa_flags_offset_over_threshold():
    recs = [_rec(exif_lat=45.0, exif_lon=-103.0, feature_lat=45.0,
                 feature_lon=-103.0, offset_m=250.0),
            _rec(exif_lat=45.0, exif_lon=-103.0, feature_lat=45.0,
                 feature_lon=-103.0, offset_m=20.0)]
    qa = QACollector()
    s = evaluate_photo_qa(recs, qa, max_offset_m=100.0)
    assert s["checked_offset"] == 2 and s["flagged_offset"] == 1
    assert any(r.category == "photo_far_from_feature" for r in qa.records)


def test_qa_flags_date_mismatch_day_level():
    recs = [_rec(taken_at="2026-05-05T08:17:36",
                 feature_edited_at="2026-05-09T14:00:00+00:00"),   # 4 days
            _rec(taken_at="2026-05-05T23:59:00",
                 feature_edited_at="2026-05-06T00:10:00+00:00")]   # ±1 ok
    qa = QACollector()
    s = evaluate_photo_qa(recs, qa)
    assert s["checked_date"] == 2 and s["flagged_date"] == 1
    assert any(r.category == "photo_date_mismatch" for r in qa.records)


def test_qa_missing_gps_and_unreadable_inventory():
    recs = [_rec(), _rec(exif_error="unreadable image: nope")]
    qa = QACollector()
    s = evaluate_photo_qa(recs, qa)
    assert s["missing_gps"] == 1 and s["unreadable"] == 1
    cats = {r.category for r in qa.records}
    assert {"photo_missing_gps", "photo_unreadable"} <= cats


def test_qa_geometryless_manifest_skips_with_info():
    recs = [_rec(exif_lat=45.0, exif_lon=-103.0)]
    qa = QACollector()
    s = evaluate_photo_qa(recs, qa)
    assert s["checked_offset"] == 0
    assert any(r.severity == "INFO" and r.category == "geometry_checks_skipped"
               for r in qa.records)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_photo_metadata.py -q`
Expected: FAIL — `evaluate_photo_qa` not defined.

- [ ] **Step 3: Implement (append to `photo_metadata.py`)**

```python
def evaluate_photo_qa(records: list[PhotoRecord], qa: QACollector, *,
                      max_offset_m: float = 100.0) -> dict:
    """Cross-check EXIF metadata against the manifest's feature-side data.

    Distance and date checks each run only where both sides exist; a
    manifest harvested before the geometry fill gets one INFO, not a wall
    of failures.
    """
    from datetime import datetime

    s = {"n_photos": len(records), "checked_offset": 0, "flagged_offset": 0,
         "checked_date": 0, "flagged_date": 0, "missing_gps": 0,
         "unreadable": 0}
    any_feature_geom = any(r.feature_lat is not None for r in records)
    for r in records:
        name = Path(r.saved_path).name
        if r.exif_error:
            s["unreadable"] += 1
            qa.add(SEV_WARNING, "photo_unreadable", f"{name}: {r.exif_error}")
            continue
        if r.exif_lat is None or r.exif_lon is None:
            s["missing_gps"] += 1
            qa.add(SEV_WARNING, "photo_missing_gps",
                   f"{name}: no GPS in EXIF")
        if r.offset_m is not None:
            s["checked_offset"] += 1
            if r.offset_m > max_offset_m:
                s["flagged_offset"] += 1
                qa.add(SEV_WARNING, "photo_far_from_feature",
                       f"{name}: photo GPS is {r.offset_m:.0f} m from its "
                       f"feature (OID {r.objectid}, limit {max_offset_m:.0f} m)")
        if r.taken_at and r.feature_edited_at:
            try:
                taken = datetime.fromisoformat(r.taken_at).date()
                edited = datetime.fromisoformat(r.feature_edited_at).date()
            except ValueError:
                pass
            else:
                s["checked_date"] += 1
                if abs((taken - edited).days) > 1:
                    s["flagged_date"] += 1
                    qa.add(SEV_WARNING, "photo_date_mismatch",
                           f"{name}: taken {taken} but feature edited "
                           f"{edited} (OID {r.objectid})")
    if records and not any_feature_geom:
        qa.add(SEV_INFO, "geometry_checks_skipped",
               "manifest has no feature geometry — distance checks skipped "
               "(re-harvest with current AutoGIS to enable)")
    return s
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_photo_metadata.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/photo_metadata.py tests/envmon/test_photo_metadata.py
git commit -m "feat(envmon): photo-vs-feature QA evaluation (offset, date, inventory)"
```

---

### Task 4: Points emitters — CSV + GeoJSON

**Files:**
- Create: `autogis/core/envmon/photo_points.py`
- Test: `tests/envmon/test_photo_points.py`

**Interfaces:**
- Consumes: `PhotoRecord` (Task 1).
- Produces: `write_points_csv(records, path: Path) -> int` and `write_points_geojson(records, path: Path) -> int` (both return the number of points written; both write valid EMPTY outputs for zero GPS-bearing records). Column order constant `POINT_FIELDS` (list). Also `gps_records(records) -> list[PhotoRecord]` used by Task 5.

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_photo_points.py`:

```python
import csv
import json
from pathlib import Path

from autogis.core.envmon.photo_metadata import PhotoRecord
from autogis.core.envmon.photo_points import (
    POINT_FIELDS, write_points_csv, write_points_geojson)


def _rec(**kw):
    base = dict(objectid=2, attachment_id=7, source_table="Obs", group="G",
                saved_path="C:/h/G/p.jpg", exif_lat=45.874, exif_lon=-103.487,
                heading_deg=231.5, heading_ref="T",
                taken_at="2026-05-05T08:17:36", camera="samsung SM-X308U",
                feature_lat=45.875, feature_lon=-103.487, offset_m=111.2)
    base.update(kw)
    return PhotoRecord(**base)


def test_points_csv(tmp_path):
    out = tmp_path / "points.csv"
    n = write_points_csv([_rec(), _rec(exif_lat=None, exif_lon=None)], out)
    assert n == 1
    rows = list(csv.DictReader(out.open(newline="", encoding="utf-8")))
    assert len(rows) == 1
    assert list(rows[0]) == POINT_FIELDS
    assert rows[0]["lat"] == "45.874" and rows[0]["heading_deg"] == "231.5"
    assert rows[0]["objectid"] == "2"


def test_points_csv_empty_still_has_header(tmp_path):
    out = tmp_path / "points.csv"
    assert write_points_csv([], out) == 0
    rows = out.read_text(encoding="utf-8").strip().splitlines()
    assert rows == [",".join(POINT_FIELDS)]


def test_points_geojson(tmp_path):
    out = tmp_path / "points.geojson"
    n = write_points_geojson([_rec()], out)
    assert n == 1
    fc = json.loads(out.read_text(encoding="utf-8"))
    assert fc["type"] == "FeatureCollection"
    f = fc["features"][0]
    assert f["geometry"] == {"type": "Point",
                             "coordinates": [-103.487, 45.874]}
    assert f["properties"]["heading_deg"] == 231.5
    assert f["properties"]["photo_path"] == "C:/h/G/p.jpg"


def test_points_geojson_empty(tmp_path):
    out = tmp_path / "points.geojson"
    assert write_points_geojson([], out) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["features"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_photo_points.py -q`
Expected: ImportError — module does not exist.

- [ ] **Step 3: Implement `autogis/core/envmon/photo_points.py`**

```python
"""photo_points.py — spatial exports of harvest photo EXIF metadata.

One point per GPS-bearing photo: CSV, GeoJSON (this task) and KMZ (Task 5).
All stdlib except the KMZ thumbnails (Pillow via the shared
``prepare_image_bytes`` helper). No arcpy. No arcgis.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from autogis.core.envmon.photo_metadata import PhotoRecord

POINT_FIELDS = ["photo_path", "source_table", "objectid", "attachment_id",
                "group", "lat", "lon", "heading_deg", "heading_ref",
                "taken_at", "camera", "feature_lat", "feature_lon",
                "offset_m"]


def gps_records(records: list[PhotoRecord]) -> list[PhotoRecord]:
    return [r for r in records
            if r.exif_lat is not None and r.exif_lon is not None]


def _props(r: PhotoRecord) -> dict:
    return {"photo_path": r.saved_path, "source_table": r.source_table,
            "objectid": r.objectid, "attachment_id": r.attachment_id,
            "group": r.group, "lat": r.exif_lat, "lon": r.exif_lon,
            "heading_deg": r.heading_deg, "heading_ref": r.heading_ref,
            "taken_at": r.taken_at, "camera": r.camera,
            "feature_lat": r.feature_lat, "feature_lon": r.feature_lon,
            "offset_m": round(r.offset_m, 1) if r.offset_m is not None
            else None}


def write_points_csv(records: list[PhotoRecord], path: Path) -> int:
    pts = gps_records(records)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=POINT_FIELDS)
        w.writeheader()
        for r in pts:
            w.writerow({k: ("" if v is None else v)
                        for k, v in _props(r).items()})
    return len(pts)


def write_points_geojson(records: list[PhotoRecord], path: Path) -> int:
    pts = gps_records(records)
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Point",
                      "coordinates": [r.exif_lon, r.exif_lat]},
         "properties": {k: v for k, v in _props(r).items()
                        if k not in ("lat", "lon")}}
        for r in pts]}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fc, indent=2), encoding="utf-8")
    return len(pts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_photo_points.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/photo_points.py tests/envmon/test_photo_points.py
git commit -m "feat(envmon): photo-points CSV + GeoJSON emitters"
```

---

### Task 5: KMZ emitter

**Files:**
- Modify: `autogis/core/envmon/photo_points.py` (add `write_kmz`)
- Test: `tests/envmon/test_photo_points.py` (append)

**Interfaces:**
- Consumes: `gps_records`, `PhotoRecord`; `prepare_image_bytes(path, box) -> Optional[bytes]` from `autogis.core.envmon.well_inspection_photo_report` (existing, Pillow lazy inside).
- Produces: `write_kmz(records, path: Path, *, thumb_px: int = 800) -> int` (placemark count; valid empty KMZ for zero points).

- [ ] **Step 1: Write the failing tests (append to `tests/envmon/test_photo_points.py`)**

```python
import xml.etree.ElementTree as ET
import zipfile

import pytest

from autogis.core.envmon.photo_points import write_kmz

_KMLNS = "{http://www.opengis.net/kml/2.2}"


def test_kmz_placemarks_and_thumbnails(tmp_path, make_photo_jpeg):
    p = make_photo_jpeg(name="spring.jpg", directory=tmp_path / "G")
    out = tmp_path / "photos.kmz"
    n = write_kmz([_rec(saved_path=str(p)),
                   _rec(exif_lat=None, exif_lon=None)], out)
    assert n == 1
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "doc.kml" in names and "files/thumb_0.jpg" in names
        root = ET.fromstring(zf.read("doc.kml"))
    pms = root.findall(f".//{_KMLNS}Placemark")
    assert len(pms) == 1
    coords = pms[0].find(f".//{_KMLNS}coordinates").text.strip()
    assert coords.startswith("-103.487,45.874")
    assert pms[0].find(f".//{_KMLNS}heading").text == "231.5"
    assert "files/thumb_0.jpg" in pms[0].find(f".//{_KMLNS}description").text


def test_kmz_missing_photo_file_placemark_without_image(tmp_path):
    out = tmp_path / "photos.kmz"
    n = write_kmz([_rec(saved_path=str(tmp_path / "gone.jpg"))], out)
    assert n == 1
    with zipfile.ZipFile(out) as zf:
        assert [n2 for n2 in zf.namelist() if n2.startswith("files/")] == []


def test_kmz_empty(tmp_path):
    out = tmp_path / "photos.kmz"
    assert write_kmz([], out) == 0
    with zipfile.ZipFile(out) as zf:
        ET.fromstring(zf.read("doc.kml"))  # valid, just no placemarks
```

Note: `test_kmz_placemarks_and_thumbnails` uses the `make_photo_jpeg` fixture (Pillow-gated via its own importorskip); `test_kmz_missing_photo_file...` must not require Pillow — `prepare_image_bytes` returns None for a missing file before importing PIL? It does NOT (import happens first) — so guard: in `write_kmz`, check `Path(r.saved_path).is_file()` before calling `prepare_image_bytes`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_photo_points.py -q`
Expected: FAIL — `write_kmz` not defined.

- [ ] **Step 3: Implement (append to `photo_points.py`)**

```python
from xml.sax.saxutils import escape


def _kml_placemark(r: PhotoRecord, thumb_name: str | None) -> str:
    name = escape(Path(r.saved_path).name)
    lines = [f"Group: {r.group}", f"Source: {r.source_table} OID {r.objectid}"]
    if r.taken_at:
        lines.append(f"Taken: {r.taken_at}")
    if r.heading_deg is not None:
        ref = " (magnetic)" if r.heading_ref == "M" else ""
        lines.append(f"Direction: {r.heading_deg:.0f}\u00b0{ref}")
    if r.camera:
        lines.append(f"Camera: {r.camera}")
    img = (f'<img src="{thumb_name}" width="400"/><br/>'
           if thumb_name else "")
    body = img + "<br/>".join(escape(s) for s in lines)
    heading = (f"<Style><IconStyle><heading>{r.heading_deg:g}</heading>"
               f"</IconStyle></Style>" if r.heading_deg is not None else "")
    return (f"<Placemark><name>{name}</name>{heading}"
            f"<description><![CDATA[{body}]]></description>"
            f"<Point><coordinates>{r.exif_lon:g},{r.exif_lat:g},0"
            f"</coordinates></Point></Placemark>")


def write_kmz(records: list[PhotoRecord], path: Path, *,
              thumb_px: int = 800) -> int:
    """Google Earth KMZ: one placemark per GPS-bearing photo, thumbnail in
    the description (skipped when the file is missing or undecodable)."""
    import zipfile

    from autogis.core.envmon.well_inspection_photo_report import (
        prepare_image_bytes)

    pts = gps_records(records)
    placemarks, thumbs = [], []
    for i, r in enumerate(pts):
        data = (prepare_image_bytes(Path(r.saved_path), (thumb_px, thumb_px))
                if Path(r.saved_path).is_file() else None)
        thumb_name = None
        if data is not None:
            thumb_name = f"files/thumb_{i}.jpg"
            thumbs.append((thumb_name, data))
        placemarks.append(_kml_placemark(r, thumb_name))
    kml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           f'<name>Harvest photos</name>{"".join(placemarks)}'
           "</Document></kml>")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", kml)
        for name, data in thumbs:
            zf.writestr(name, data)
    return len(pts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_photo_points.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/photo_points.py tests/envmon/test_photo_points.py
git commit -m "feat(envmon): KMZ photo placemark export with embedded thumbnails"
```

---

### Task 6: Photographic log (xlsx / html / docx) + `report-docx` extra

**Files:**
- Create: `autogis/core/envmon/photo_log.py`
- Modify: `pyproject.toml` (add `report-docx` optional extra)
- Test: `tests/envmon/test_photo_log.py`

**Interfaces:**
- Consumes: `PhotoRecord`; `prepare_image_bytes` (existing); `autogis.core.common.report_html` (`render_document`, `table`, `photo_grid` — `photo_grid` takes `(src, caption)` tuples).
- Produces: `write_log(records, out_path: Path, *, fmt: str = "xlsx", title: str = "Photographic Log") -> int` dispatching to `_write_xlsx` / `_write_html` / `_write_docx` by `fmt`; returns photo count; raises `ValueError` for unknown fmt. `DOCX_HINT` constant.

- [ ] **Step 1: Add the extra to `pyproject.toml`**

In `[project.optional-dependencies]`, after the `report = [...]` line:

```toml
report-docx = ["python-docx", "Pillow>=9.0"]   # DOCX photographic log (envmon photos log --format docx)
```

- [ ] **Step 2: Write the failing tests**

Create `tests/envmon/test_photo_log.py`:

```python
from pathlib import Path

import pytest

from autogis.core.envmon.photo_metadata import PhotoRecord
from autogis.core.envmon.photo_log import write_log


def _rec(path, **kw):
    base = dict(objectid=2, attachment_id=7, source_table="Obs",
                group="G/SeepSpring", saved_path=str(path),
                exif_lat=45.874, exif_lon=-103.487, heading_deg=231.5,
                heading_ref="T", taken_at="2026-05-05T08:17:36",
                camera="samsung SM-X308U")
    base.update(kw)
    return PhotoRecord(**base)


def test_log_xlsx(tmp_path, make_photo_jpeg):
    pytest.importorskip("openpyxl")
    p = make_photo_jpeg(directory=tmp_path / "G")
    out = tmp_path / "log.xlsx"
    n = write_log([_rec(p)], out, fmt="xlsx")
    assert n == 1
    from openpyxl import load_workbook
    wb = load_workbook(out)
    ws = wb.active
    assert ws.cell(row=1, column=1).value == "Photo #"
    assert ws.cell(row=2, column=1).value == 1
    assert "SW" in ws.cell(row=2, column=5).value      # 231.5° -> SW
    assert ws.cell(row=2, column=7).value in (None, "")  # blank Description


def test_log_html(tmp_path, make_photo_jpeg):
    p = make_photo_jpeg(directory=tmp_path / "G")
    out = tmp_path / "log.html"
    n = write_log([_rec(p)], out, fmt="html", title="RILEY PASS photos")
    assert n == 1
    html = out.read_text(encoding="utf-8")
    assert "RILEY PASS photos" in html
    assert "data:image/jpeg;base64," in html
    assert "231" in html and "45.874" in html


def test_log_docx(tmp_path, make_photo_jpeg):
    pytest.importorskip("docx")
    p = make_photo_jpeg(directory=tmp_path / "G")
    out = tmp_path / "log.docx"
    n = write_log([_rec(p)], out, fmt="docx")
    assert n == 1
    import docx
    d = docx.Document(str(out))
    text = "\n".join(par.text for par in d.paragraphs)
    assert "Photo 1" in text and "Description:" in text


def test_log_unknown_format(tmp_path):
    with pytest.raises(ValueError):
        write_log([], tmp_path / "x.pdf", fmt="pdf")


def test_log_photo_without_gps_or_file(tmp_path):
    # No GPS, file missing on disk: still a log row, blank coords, no crash.
    out = tmp_path / "log.html"
    n = write_log([_rec(tmp_path / "gone.jpg", exif_lat=None, exif_lon=None,
                        heading_deg=None, taken_at=None)], out, fmt="html")
    assert n == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_photo_log.py -q`
Expected: ImportError — module does not exist.

- [ ] **Step 4: Implement `autogis/core/envmon/photo_log.py`**

```python
"""photo_log.py — photographic log appendix from harvest photo metadata.

The standard consulting deliverable (photo #, thumbnail, date, direction,
coordinates, blank description column for hand-editing) in three formats:
xlsx (openpyxl, mirrors Tool 7.4's embedding path), html
(``report_html``), docx (python-docx via the ``report-docx`` extra).
Image and docx libraries are lazy-imported. No arcpy. No arcgis.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

from autogis.core.envmon.photo_metadata import PhotoRecord
from autogis.core.envmon.well_inspection_photo_report import (
    prepare_image_bytes)

DOCX_HINT = ("python-docx is required for --format docx; install with: "
             "pip install \"autogis[report-docx]\"")
_CARDINALS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
_THUMB_BOX = (800, 800)
_XLSX_BOX = (300, 225)


def _cardinal(deg: float) -> str:
    return _CARDINALS[round(deg / 45.0) % 8]


def _direction(r: PhotoRecord) -> str:
    if r.heading_deg is None:
        return ""
    ref = " (magnetic)" if r.heading_ref == "M" else ""
    return f"{r.heading_deg:.0f}\u00b0 {_cardinal(r.heading_deg)}{ref}"


def _coords(r: PhotoRecord) -> str:
    if r.exif_lat is None or r.exif_lon is None:
        return ""
    return f"{r.exif_lat:.6f}, {r.exif_lon:.6f}"


def _feature(r: PhotoRecord) -> str:
    oid = f" OID {r.objectid}" if r.objectid is not None else ""
    return f"{r.group}{oid}"


def _bytes_of(r: PhotoRecord, box) -> bytes | None:
    p = Path(r.saved_path)
    return prepare_image_bytes(p, box) if p.is_file() else None


def write_log(records: list[PhotoRecord], out_path: Path, *,
              fmt: str = "xlsx", title: str = "Photographic Log") -> int:
    writer = {"xlsx": _write_xlsx, "html": _write_html,
              "docx": _write_docx}.get(fmt)
    if writer is None:
        raise ValueError(f"unknown log format: {fmt!r} (xlsx|html|docx)")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer(records, out_path, title)
    return len(records)


def _write_xlsx(records, out_path, title):
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Photo Log"
    headers = ["Photo #", "Image", "Group / Feature", "Taken", "Direction",
               "Coordinates", "Description", "Source Path"]
    ws.append(headers)
    for c, _ in enumerate(headers, start=1):
        ws.cell(row=1, column=c).font = Font(bold=True)
    widths = [8, 44, 28, 20, 16, 24, 40, 50]
    for c, wd in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(c)].width = wd
    wrap = Alignment(wrap_text=True, vertical="top")
    for i, r in enumerate(records, start=1):
        row_no = i + 1
        ws.cell(row=row_no, column=1, value=i)
        data = _bytes_of(r, _XLSX_BOX)
        if data is not None:
            img = XLImage(io.BytesIO(data))
            ws.add_image(img, f"B{row_no}")
            ws.row_dimensions[row_no].height = _XLSX_BOX[1] * 0.75
        for col, val in ((3, _feature(r)), (4, r.taken_at or ""),
                         (5, _direction(r)), (6, _coords(r)), (7, ""),
                         (8, r.saved_path)):
            ws.cell(row=row_no, column=col, value=val).alignment = wrap
    wb.save(out_path)


def _write_html(records, out_path, title):
    from autogis.core.common import report_html as rh

    images, rows = [], []
    for i, r in enumerate(records, start=1):
        data = _bytes_of(r, _THUMB_BOX)
        caption = (f"Photo {i} \u2014 {_feature(r)}"
                   + (f" \u2014 {r.taken_at}" if r.taken_at else "")
                   + (f" \u2014 {_direction(r)}" if r.heading_deg is not None
                      else ""))
        if data is not None:
            src = ("data:image/jpeg;base64,"
                   + base64.b64encode(data).decode("ascii"))
            images.append((src, caption))
        rows.append([i, _feature(r), r.taken_at or "", _direction(r),
                     _coords(r), "", Path(r.saved_path).name])
    out_path.write_text(
        rh.render_document(title=title, sections=[
            rh.section("Photos", rh.photo_grid(images)),
            rh.section("Index", rh.table(
                ["Photo #", "Group / Feature", "Taken", "Direction",
                 "Coordinates", "Description", "File"], rows)),
        ]), encoding="utf-8")


def _write_docx(records, out_path, title):
    try:
        import docx
        from docx.shared import Inches
    except ImportError as exc:
        raise ImportError(DOCX_HINT) from exc
    doc = docx.Document()
    doc.add_heading(title, level=1)
    for i, r in enumerate(records, start=1):
        data = _bytes_of(r, _THUMB_BOX)
        if data is not None:
            doc.add_picture(io.BytesIO(data), width=Inches(4.5))
        meta = [f"Photo {i} \u2014 {_feature(r)}"]
        if r.taken_at:
            meta.append(f"Taken: {r.taken_at}")
        if r.heading_deg is not None:
            meta.append(f"Direction: {_direction(r)}")
        if _coords(r):
            meta.append(f"Coordinates: {_coords(r)}")
        p = doc.add_paragraph("\n".join(meta))
        p.runs[0].bold = True
        doc.add_paragraph("Description: ")
        doc.add_paragraph()
    doc.save(str(out_path))
```

(`render_document`'s signature is `(*, title, subtitle="", meta=None, sections=(), generated="")` — verified against `autogis/core/common/report_html.py:105`; `sections` takes the already-rendered section HTML strings.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_photo_log.py -q`
Expected: PASS (docx test skips unless python-docx is installed; install it into the dev venv with `python -m pip install python-docx` so it actually runs at least once locally, then note the result).

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/photo_log.py tests/envmon/test_photo_log.py pyproject.toml
git commit -m "feat(envmon): photographic log emitter (xlsx/html/docx) + report-docx extra"
```

---

### Task 7: CLI subgroup, README, ADR

**Files:**
- Modify: `autogis/adapters/cli.py` (new `photos` subgroup under `envmon`)
- Modify: `README.md` (Runtime Matrix rows for the four commands)
- Create: `docs/adr/NNNN-harvest-photo-metadata-suite.md` (number reserved at execution time)
- Test: `tests/envmon/test_cli_photos.py`

**Interfaces:**
- Consumes: `load_photo_records`, `evaluate_photo_qa` (photo_metadata); `write_points_csv`, `write_points_geojson`, `write_kmz` (photo_points); `write_log` (photo_log); existing CLI helpers `qa_report_options`, `_render_qa` (`autogis/adapters/cli.py:25` and `:1859`), subgroup idiom `@envmon.group(...)` (see `coc` at `cli.py:2538`).
- Produces: commands `autogis envmon photos points|qa|log|kmz`.

- [ ] **Step 1: Write the failing CLI tests**

Create `tests/envmon/test_cli_photos.py`:

```python
import json
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis as cli


def _harvest(tmp_path, make_photo_jpeg, geometry=None):
    p = make_photo_jpeg(name="spring.jpg", directory=tmp_path / "Obs" / "S")
    row = {"objectid": 2, "attachment_id": 7, "original_name": "Photo 1.jpg",
           "saved_path": str(p), "size": 5, "status": "downloaded",
           "error": None, "disposition": "downloaded", "checksum": None,
           "algorithm": None, "geometry": geometry,
           "source_table": "Obs", "relationship_id": None,
           "feature_edited_at": None}
    (tmp_path / "manifest.json").write_text(json.dumps([row]),
                                            encoding="utf-8")
    return tmp_path


def test_photos_points(tmp_path, make_photo_jpeg):
    h = _harvest(tmp_path, make_photo_jpeg)
    out_csv = tmp_path / "pts.csv"
    out_gj = tmp_path / "pts.geojson"
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "points", "--harvest-dir", str(h),
        "--out-csv", str(out_csv), "--out-geojson", str(out_gj)])
    assert res.exit_code == 0, res.output
    assert out_csv.exists() and out_gj.exists()
    assert "1 point(s)" in res.output


def test_photos_points_requires_an_output(tmp_path, make_photo_jpeg):
    h = _harvest(tmp_path, make_photo_jpeg)
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "points", "--harvest-dir", str(h)])
    assert res.exit_code != 0
    assert "--out-csv" in res.output


def test_photos_qa_geometryless_manifest(tmp_path, make_photo_jpeg):
    h = _harvest(tmp_path, make_photo_jpeg)
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "qa", "--harvest-dir", str(h)])
    assert res.exit_code == 0, res.output
    assert "geometry_checks_skipped" in res.output


def test_photos_qa_offset_flag(tmp_path, make_photo_jpeg):
    h = _harvest(tmp_path, make_photo_jpeg,
                 geometry={"lat": 45.9, "lon": -103.487})  # ~2.9 km away
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "qa", "--harvest-dir", str(h),
        "--fail-on", "warning"])
    assert res.exit_code != 0
    assert "photo_far_from_feature" in res.output


def test_photos_log_and_kmz(tmp_path, make_photo_jpeg):
    h = _harvest(tmp_path, make_photo_jpeg)
    out_log = tmp_path / "log.html"
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "log", "--harvest-dir", str(h),
        "--out", str(out_log), "--format", "html"])
    assert res.exit_code == 0, res.output
    assert out_log.exists()
    out_kmz = tmp_path / "p.kmz"
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "kmz", "--harvest-dir", str(h),
        "--out", str(out_kmz)])
    assert res.exit_code == 0, res.output
    with zipfile.ZipFile(out_kmz) as zf:
        assert "doc.kml" in zf.namelist()


def test_photos_missing_manifest_is_clean_error(tmp_path):
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "qa", "--harvest-dir", str(tmp_path)])
    assert res.exit_code != 0
    assert "manifest" in res.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_cli_photos.py -q`
Expected: FAIL — no such command `photos`.

- [ ] **Step 3: Implement the CLI subgroup (append near the other envmon subgroups in `autogis/adapters/cli.py`)**

```python
@envmon.group("photos")
def photos_group():
    """Photo-metadata tools over a harvest output folder (EXIF-driven).

    All headless: they read the harvest manifest + the photo files' EXIF
    (GPS, compass heading, timestamp). Requires Pillow
    (pip install "autogis[report]").
    """


def _load_photo_records_or_fail(harvest_dir, qa):
    from autogis.core.envmon.photo_metadata import load_photo_records
    try:
        return load_photo_records(Path(harvest_dir), qa)
    except (FileNotFoundError, ImportError) as exc:
        raise click.ClickException(str(exc))


@photos_group.command("points")
@click.option("--harvest-dir", required=True,
              type=click.Path(exists=True, file_okay=False),
              help="Harvest output directory (contains manifest.csv/json).")
@click.option("--out-csv", default=None, type=click.Path(),
              help="Write photo points CSV here.")
@click.option("--out-geojson", default=None, type=click.Path(),
              help="Write photo points GeoJSON here.")
@qa_report_options
def photos_points_cmd(harvest_dir, out_csv, out_geojson, report, fail_on):
    """One point per GPS-bearing photo (EXIF position + heading)."""
    if not out_csv and not out_geojson:
        raise click.UsageError("pass --out-csv and/or --out-geojson")
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.photo_points import (
        write_points_csv, write_points_geojson)
    qa = QACollector()
    records = _load_photo_records_or_fail(harvest_dir, qa)
    n = 0
    if out_csv:
        n = write_points_csv(records, Path(out_csv))
    if out_geojson:
        n = write_points_geojson(records, Path(out_geojson))
    skipped = len(records) - n
    click.echo(f"Photo points: {n} point(s) from {len(records)} photo(s)"
               + (f" ({skipped} without GPS)" if skipped else ""))
    _render_qa(qa, report, fail_on)


@photos_group.command("qa")
@click.option("--harvest-dir", required=True,
              type=click.Path(exists=True, file_okay=False),
              help="Harvest output directory (contains manifest.csv/json).")
@click.option("--max-offset-m", default=100.0, show_default=True,
              help="Flag photos whose EXIF GPS is farther than this from "
                   "their source feature.")
@qa_report_options
def photos_qa_cmd(harvest_dir, max_offset_m, report, fail_on):
    """Cross-check photo EXIF against the features they are attached to."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.photo_metadata import evaluate_photo_qa
    qa = QACollector()
    records = _load_photo_records_or_fail(harvest_dir, qa)
    s = evaluate_photo_qa(records, qa, max_offset_m=max_offset_m)
    click.echo(f"Photo QA: {s['n_photos']} photo(s); "
               f"offset {s['flagged_offset']}/{s['checked_offset']} flagged; "
               f"date {s['flagged_date']}/{s['checked_date']} flagged; "
               f"{s['missing_gps']} missing GPS; "
               f"{s['unreadable']} unreadable")
    _render_qa(qa, report, fail_on)


@photos_group.command("log")
@click.option("--harvest-dir", required=True,
              type=click.Path(exists=True, file_okay=False),
              help="Harvest output directory (contains manifest.csv/json).")
@click.option("--out", "out_path", required=True, type=click.Path(),
              help="Output file (extension need not match --format).")
@click.option("--format", "fmt", default="xlsx", show_default=True,
              type=click.Choice(["xlsx", "html", "docx"]))
@click.option("--title", default="Photographic Log", show_default=True)
@qa_report_options
def photos_log_cmd(harvest_dir, out_path, fmt, title, report, fail_on):
    """Photographic log appendix (thumbnail, date, direction, coordinates)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.photo_log import write_log
    qa = QACollector()
    records = _load_photo_records_or_fail(harvest_dir, qa)
    try:
        n = write_log(records, Path(out_path), fmt=fmt, title=title)
    except ImportError as exc:
        raise click.ClickException(str(exc))
    click.echo(f"Photo log: {n} photo(s) -> {out_path} ({fmt})")
    _render_qa(qa, report, fail_on)


@photos_group.command("kmz")
@click.option("--harvest-dir", required=True,
              type=click.Path(exists=True, file_okay=False),
              help="Harvest output directory (contains manifest.csv/json).")
@click.option("--out", "out_path", required=True, type=click.Path(),
              help="Output .kmz path.")
@click.option("--thumb-px", default=800, show_default=True,
              help="Max thumbnail edge (pixels) embedded in the KMZ.")
@qa_report_options
def photos_kmz_cmd(harvest_dir, out_path, thumb_px, report, fail_on):
    """Google Earth KMZ of GPS-bearing photos with view-direction styling."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.photo_points import write_kmz
    qa = QACollector()
    records = _load_photo_records_or_fail(harvest_dir, qa)
    n = write_kmz(records, Path(out_path), thumb_px=thumb_px)
    click.echo(f"KMZ: {n} placemark(s) -> {out_path}")
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_cli_photos.py -q`
Expected: all PASS.

- [ ] **Step 5: README Runtime Matrix + ADR**

- Open `README.md`, find the Runtime Matrix table, and add four HEADLESS rows following the exact format of neighboring rows: `envmon photos points`, `envmon photos qa`, `envmon photos log`, `envmon photos kmz` (note "openpyxl/Pillow; python-docx optional" for `log`).
- Reserve the next free ADR number: run `python .claude/coordination/coord_cli.py reserve-adr` from the repo root (if that subcommand is unavailable, scan `docs/adr/` on origin/main AND every open PR's changed files for the highest `NNNN-`, then take the next; per `docs/adr/README.md`).
- Write `docs/adr/NNNN-harvest-photo-metadata-suite.md` (format per `docs/adr/README.md`, Status: Proposed): decision = EXIF extraction core + four headless emitters + harvester fill of reserved `geometry`/`checksum` columns + new `feature_edited_at` column; link the spec (`docs/superpowers/specs/2026-08-12-harvest-photo-metadata-suite-design.md`); record the out-of-scope list (dedup report, live backfill, declination correction, non-mercator SR conversion) and the manifest back-compat contract (all new columns optional, appended last).
- Add both to the ADR index if `docs/adr/README.md` carries one (check how previous ADRs registered themselves).

- [ ] **Step 6: Full suite + real-console smoke**

Run: `python -m pytest -q` (expect green; count grows by the new tests).
Then a real Windows console smoke against the actual example output (CliRunner masks cp1252 console crashes — Phase 6 lesson):

```bash
python -m autogis envmon photos qa --harvest-dir "C:/Users/ichbi/OneDrive/Desktop/RILEY_PASS_SEEPS_SPRINGS_PHOTOS"
python -m autogis envmon photos points --harvest-dir "C:/Users/ichbi/OneDrive/Desktop/RILEY_PASS_SEEPS_SPRINGS_PHOTOS" --out-csv "%TEMP%/riley_points.csv" --out-geojson "%TEMP%/riley_points.geojson"
python -m autogis envmon photos kmz --harvest-dir "C:/Users/ichbi/OneDrive/Desktop/RILEY_PASS_SEEPS_SPRINGS_PHOTOS" --out "%TEMP%/riley.kmz"
python -m autogis envmon photos log --harvest-dir "C:/Users/ichbi/OneDrive/Desktop/RILEY_PASS_SEEPS_SPRINGS_PHOTOS" --out "%TEMP%/riley_log.xlsx"
```

(Adjust the temp paths to the session scratchpad; the point is: real console, real photos, geometry-less manifest → expect the `geometry_checks_skipped` INFO and real point/log/KMZ outputs.)

- [ ] **Step 7: Commit**

```bash
git add autogis/adapters/cli.py README.md docs/adr/ tests/envmon/test_cli_photos.py
git commit -m "feat(cli): envmon photos subgroup (points/qa/log/kmz) + README matrix + ADR"
```

---

## Post-implementation gates (before PR is ready)

1. **Five-probe table** in the PR description (`docs/pr-review-failure-mode-audit.md`): classify `BOUNDARY_SHAPE`, `CONTRACT_REACHABILITY`, `IDENTITY_PROVENANCE`, `SIDE_EFFECT_SAFETY`, `ENVIRONMENT_SEAM` each exactly once with a minimal adversarial command or regression test at the real seam (the Task 7 real-console smoke against RILEY_PASS covers ENVIRONMENT_SEAM; the geometry-less-manifest QA run covers CONTRACT_REACHABILITY for the back-compat contract).
2. **envmon-spec-checker** subagent over the diff (arcpy-free invariant, canonical config, DRAFT markers untouched).
3. **Live smoke harvest** (owner-gated leg, may trail the PR): one real harvest against an AGOL layer with the Pro conda env or `[cloud]` venv to confirm `return_geometry=True` payloads and the geometry/EditDate fill on real services — the fakes cannot prove the arcgis wire format. Record the result in the PR. `arcpy-doc-verifier` is N/A (no arcpy calls — `arcgis` Python API only).
4. **pr-reviewer** against the exact final head; resolve every FAIL before merge; merge needs owner sign-off (do not self-merge).
5. Any bug found along the way in committed code → GitHub issue (check for duplicates first).
