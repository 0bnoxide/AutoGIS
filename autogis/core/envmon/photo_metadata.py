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
import posixpath
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
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


def _dms_to_dd(dms, ref, *, refs: tuple[str, str], limit: float
               ) -> Optional[float]:
    if dms is None and ref is None:
        return None
    if dms is None or ref not in refs:
        raise ValueError("GPS coordinate has missing or invalid hemisphere")
    try:
        d, m, s = (float(v) for v in dms)
    except (TypeError, ValueError, ZeroDivisionError):
        raise ValueError("GPS coordinate must contain three numbers") from None
    if (not all(math.isfinite(v) for v in (d, m, s))
            or d < 0 or not 0 <= m < 60 or not 0 <= s < 60):
        raise ValueError("GPS coordinate has invalid DMS values")
    dd = d + m / 60.0 + s / 3600.0
    if dd > limit:
        raise ValueError("GPS coordinate is outside its valid range")
    return -dd if ref == refs[1] else dd


def extract_exif(path: Path) -> dict:
    """EXIF fields of one image file; ``{"exif_error": ...}`` if unreadable."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise ImportError(PILLOW_HINT) from exc
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            gps = exif.get_ifd(0x8825)  # GPSInfo
            sub = exif.get_ifd(0x8769)  # ExifOffset
    except OSError as exc:  # UnidentifiedImageError subclasses OSError
        return {"exif_error": f"unreadable image: {exc}"}
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        return {"exif_error": f"corrupt EXIF: {exc}"}
    out: dict = {}
    errors: list[str] = []
    if not isinstance(gps, Mapping):
        errors.append("GPS IFD must be a mapping")
        gps = {}
    if not isinstance(sub, Mapping):
        errors.append("EXIF IFD must be a mapping")
        sub = {}
    try:
        lat = _dms_to_dd(
            gps.get(2), gps.get(1), refs=("N", "S"), limit=90.0)
        lon = _dms_to_dd(
            gps.get(4), gps.get(3), refs=("E", "W"), limit=180.0)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        errors.append(str(exc))
    else:
        out.update(exif_lat=lat, exif_lon=lon)
    if gps.get(17) is not None:                     # GPSImgDirection
        try:
            heading = float(gps[17])
            if not math.isfinite(heading) or not 0 <= heading < 360:
                raise ValueError("GPS image direction is outside 0..360")
            heading_ref = gps.get(16)
            if heading_ref not in ("T", "M"):
                raise ValueError(
                    "GPS image direction has missing or invalid reference")
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            errors.append(str(exc))
        else:
            out["heading_deg"] = heading
            out["heading_ref"] = heading_ref
    dto = sub.get(36867) or exif.get(306)           # DateTimeOriginal|DateTime
    if dto:
        try:
            parsed = datetime.strptime(
                str(dto).strip(), "%Y:%m:%d %H:%M:%S")
        except (TypeError, ValueError) as exc:
            errors.append(f"capture datetime: {exc}")
        else:
            out["taken_at"] = parsed.isoformat(timespec="seconds")
    try:
        make, model = exif.get(271), exif.get(272)
        if make or model:
            out["camera"] = " ".join(s for s in (str(make or "").strip(),
                                                 str(model or "").strip()) if s)
    except (TypeError, ValueError) as exc:
        errors.append(f"camera: {exc}")
    if errors:
        out["exif_error"] = "corrupt EXIF: " + "; ".join(errors)
    return out


def _int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _geom_latlon(v) -> tuple[Optional[float], Optional[float]]:
    try:
        if isinstance(v, str):
            v = json.loads(v) if v.strip() else None
        if not isinstance(v, dict):
            return None, None
        lat, lon = float(v["lat"]), float(v["lon"])
        if (not math.isfinite(lat) or not math.isfinite(lon)
                or not -90 <= lat <= 90 or not -180 <= lon <= 180):
            raise ValueError("geometry coordinate outside valid range")
        return lat, lon
    except (KeyError, TypeError, ValueError):
        # ValueError also catches json.JSONDecodeError (its subclass), so a
        # corrupt geometry cell degrades to (None, None) instead of raising
        # out of load_photo_records.
        return None, None


def _group_of(saved: str, harvest_dir: Path) -> str:
    parts = PurePosixPath(str(saved).replace("\\", "/"))
    try:
        rel = parts.relative_to(
            PurePosixPath(str(harvest_dir).replace("\\", "/")))
        return "/".join(rel.parts[:-1])
    except ValueError:
        return parts.parent.name


def _path_key(value: object) -> str:
    """Lexically normalize a manifest path without touching the filesystem."""
    return posixpath.normpath(str(value).replace("\\", "/")).casefold()


def _harvest_file_index(harvest_dir: Path) -> dict[str, Path]:
    """Index only real files whose resolved targets remain under harvest_dir."""
    files: dict[str, Path] = {}
    for candidate in harvest_dir.rglob("*"):
        try:
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            relative = resolved.relative_to(harvest_dir)
        except (OSError, RuntimeError, ValueError):
            continue
        files[_path_key(relative.as_posix())] = resolved
        files[_path_key(resolved.as_posix())] = resolved
    return files


def _manifest_path(harvest_dir: Path) -> Path:
    manifest = next((harvest_dir / name
                     for name in ("manifest.json", "manifest.csv")
                     if (harvest_dir / name).is_file()), None)
    if manifest is None:
        raise FileNotFoundError(
            f"no manifest.json/manifest.csv in {harvest_dir} — is this a "
            f"harvest output directory?")
    return manifest


def _manifest_rows(manifest: Path) -> list[dict]:
    rows = load_manifest(manifest)
    if not isinstance(rows, list):
        raise ValueError("manifest must contain a list of row objects")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("every manifest row must be an object")
    for row in rows:
        if "saved_path" not in row:
            raise ValueError("every manifest row must contain saved_path")
        saved = row["saved_path"]
        if saved is not None and not isinstance(saved, str):
            raise ValueError("manifest saved_path values must be strings or null")
        disposition = row.get("disposition") or row.get("status")
        if not isinstance(disposition, str):
            raise ValueError(
                "every manifest row must contain a string status/disposition")
    return rows


def _match_harvest_path(saved: object, files: dict[str, Path], root_key: str
                        ) -> tuple[Path | None, str | None]:
    saved_text = str(saved).replace("\\", "/")
    if ".." in PurePosixPath(saved_text).parts:
        return None, "outside"
    saved_key = _path_key(saved_text)
    matched = files.get(saved_key)
    if matched is not None:
        return matched, None
    is_absolute = (PurePosixPath(saved_text).is_absolute()
                   or (len(saved_text) >= 3 and saved_text[1:3] == ":/"))
    if is_absolute and not (saved_key == root_key
                            or saved_key.startswith(root_key + "/")):
        return None, "outside"
    return None, "missing"


def load_harvest_input_paths(harvest_dir: Path) -> tuple[Path, ...]:
    """Existing manifest inputs, matched without filesystem use of row text."""
    harvest_dir = Path(harvest_dir).resolve()
    rows = _manifest_rows(_manifest_path(harvest_dir))
    files = _harvest_file_index(harvest_dir)
    root_key = _path_key(harvest_dir.as_posix()).rstrip("/")
    matched: set[Path] = set()
    for row in rows:
        if not row.get("saved_path"):
            continue
        path, _ = _match_harvest_path(row["saved_path"], files, root_key)
        if path is not None:
            matched.add(path)
    return tuple(sorted(matched))


def _add_inventory_warnings(records: list[PhotoRecord], qa: QACollector) -> None:
    existing = {(r.severity, r.category, r.message) for r in qa.records}

    def add(category: str, message: str) -> None:
        item = (SEV_WARNING, category, message)
        if item not in existing:
            qa.add(*item)
            existing.add(item)

    for record in records:
        name = PurePosixPath(record.saved_path.replace("\\", "/")).name
        identity = (f"{record.source_table or '?'} OID {record.objectid} "
                    f"attachment {record.attachment_id} "
                    f"({record.group}/{name})")
        if record.exif_error:
            add("photo_unreadable", f"{identity}: {record.exif_error}")
            if record.exif_lat is None or record.exif_lon is None:
                continue
        if record.exif_lat is None or record.exif_lon is None:
            add("photo_missing_gps", f"{identity}: no GPS in EXIF")
        if not record.taken_at:
            add("photo_missing_datetime",
                f"{identity}: no capture datetime in EXIF")


def load_photo_records(harvest_dir: Path, qa: QACollector) -> list[PhotoRecord]:
    """Manifest rows joined with per-file EXIF, one record per usable photo."""
    harvest_dir = Path(harvest_dir).resolve()
    rows = _manifest_rows(_manifest_path(harvest_dir))
    records: list[PhotoRecord] = []
    missing, non_image, outside = [], [], 0
    files = _harvest_file_index(harvest_dir)
    root_key = _path_key(harvest_dir.as_posix()).rstrip("/")
    for row in rows:
        disposition = row.get("disposition") or row.get("status")
        saved = row.get("saved_path")
        if disposition not in _USABLE_DISPOSITIONS or not saved:
            continue
        p, reason = _match_harvest_path(saved, files, root_key)
        if p is None:
            if reason == "outside":
                outside += 1
            else:
                missing.append(PurePosixPath(
                    str(saved).replace("\\", "/")).name)
            continue
        if p.suffix.lower() not in IMAGE_SUFFIXES:
            non_image.append(p.name)
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
    if outside:
        qa.add(SEV_WARNING, "manifest_rows_outside_harvest_dir",
               f"{outside} manifest photo path(s) outside {harvest_dir} "
               "— dropped")
    _add_inventory_warnings(records, qa)
    return records


def evaluate_photo_qa(records: list[PhotoRecord], qa: QACollector, *,
                      max_offset_m: float = 100.0) -> dict:
    """Cross-check EXIF metadata against the manifest's feature-side data.

    Distance and date checks each run only where both sides exist; a
    manifest harvested before the geometry fill gets one INFO, not a wall
    of failures.
    """
    from datetime import datetime

    if not math.isfinite(max_offset_m) or max_offset_m < 0:
        raise ValueError("max_offset_m must be finite and non-negative")
    _add_inventory_warnings(records, qa)
    s = {"n_photos": len(records), "checked_offset": 0, "flagged_offset": 0,
         "checked_date": 0, "flagged_date": 0, "missing_gps": 0,
         "missing_datetime": 0, "unreadable": 0}
    any_feature_geom = any(r.feature_lat is not None for r in records)
    for r in records:
        name = Path(r.saved_path).name
        if r.exif_error:
            s["unreadable"] += 1
            if r.exif_lat is None or r.exif_lon is None:
                continue
        if r.exif_lat is None or r.exif_lon is None:
            s["missing_gps"] += 1
        if not r.taken_at:
            s["missing_datetime"] += 1
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
            except (ValueError, TypeError):
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
