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
