"""Contract-v1 Civil 3D handoff package emitter (ADR-0128).

Builds the two-entry ZIP (handoff.json + surface.landxml) defined by the
AutoGIS-Civil3D contract v1. The surface is re-emitted through
write_landxml_surface so the packaged bytes are production writer output,
and every metadata field is either declared by the source file or supplied
explicitly by the caller — never inferred. Conformance is proven solely by
the consumer repository's validator; this module never self-validates.
"""
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from autogis import __version__
from autogis.core.common.landxml import (
    parse_landxml_surface,
    read_source_metadata,
    write_landxml_surface,
)
from autogis.core.envmon.source_registry import compute_sha256

PRODUCER_NAME = "AutoGIS"
MANIFEST_UNIT_BY_LANDXML = {
    "meter": "metre",
    "foot": "international_foot",
    "USSurveyFoot": "us_survey_foot",
}
VERTICAL_UNITS = ("metre", "international_foot", "us_survey_foot")
_SOURCE_COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$")


def build_handoff_package(
        input_path, output_path, *,
        vertical_unit,
        surface_name="",
        datum_authority=None,
        datum_code=None,
        datum_name=None,
        datum_note=None,
        source_commit=None,
        overwrite=False):
    """Write a contract-v1 package ZIP and return its manifest dict."""
    source = Path(input_path)
    destination = Path(output_path)
    if source.resolve() == destination.resolve():
        raise ValueError("Input and output paths must be different.")
    if destination.exists() and not overwrite:
        raise FileExistsError(
            f"{destination} already exists; pass overwrite=True to "
            "replace it.")

    datum = _vertical_datum(
        datum_authority, datum_code, datum_name, datum_note)
    if vertical_unit not in VERTICAL_UNITS:
        raise ValueError(
            f"vertical_unit must be one of {', '.join(VERTICAL_UNITS)}, "
            f"not {vertical_unit!r}.")
    if source_commit is not None and not _SOURCE_COMMIT_RE.match(
            source_commit):
        raise ValueError(
            "source_commit must be 7-64 lowercase hex characters.")

    meta = read_source_metadata(source)
    epsg = _declared_epsg(meta.crs, source)
    if meta.linear_unit not in MANIFEST_UNIT_BY_LANDXML:
        raise ValueError(
            f"{source} declares no supported LandXML linearUnit "
            f"(found {meta.linear_unit!r}); the handoff contract never "
            "infers units.")
    horizontal_unit = MANIFEST_UNIT_BY_LANDXML[meta.linear_unit]

    emitted_elevation = (
        "meter" if meta.linear_unit == "meter" else "feet")
    if (meta.elevation_unit is not None
            and meta.elevation_unit != emitted_elevation):
        raise ValueError(
            f"{source} declares elevationUnit {meta.elevation_unit!r} but "
            f"re-emission with linearUnit {meta.linear_unit!r} writes "
            f"{emitted_elevation!r}; refusing to alter the declared "
            "vertical unit family.")
    allowed_vertical = (
        ("metre",) if emitted_elevation == "meter"
        else ("international_foot", "us_survey_foot"))
    if vertical_unit not in allowed_vertical:
        raise ValueError(
            f"vertical_unit {vertical_unit!r} contradicts the surface's "
            f"{emitted_elevation!r} elevation family; expected one of "
            f"{', '.join(allowed_vertical)}.")

    surface = parse_landxml_surface(source, surface_name=surface_name)
    with TemporaryDirectory() as tmp:
        landxml_path = Path(tmp) / "surface.landxml"
        write_landxml_surface(
            surface, landxml_path,
            crs=f"EPSG:{epsg}", linear_unit=meta.linear_unit)
        manifest = {
            "contract_version": "1.0",
            "package_id": str(uuid.uuid4()),
            "created_utc": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"),
            "producer": {"name": PRODUCER_NAME, "version": __version__},
            "surface": {
                "filename": "surface.landxml",
                "sha256": compute_sha256(landxml_path),
                "landxml_version": "1.2",
                "name": surface.name,
                "point_count": len(surface.points),
                "face_count": len(surface.faces),
            },
            "coordinate_reference": {
                "horizontal": {
                    "kind": "projected",
                    "authority": "EPSG",
                    "code": epsg,
                    "unit": horizontal_unit,
                },
                "vertical": {
                    "unit": vertical_unit,
                    "direction": "positive_up",
                    "datum": datum,
                },
            },
        }
        if source_commit is not None:
            manifest["producer"]["source_commit"] = source_commit
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(
                destination, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("handoff.json", json.dumps(manifest, indent=2))
            zf.write(landxml_path, "surface.landxml")
    return manifest


def _vertical_datum(authority, code, name, note):
    supplied = [v for v in (authority, code, name) if v is not None]
    if supplied and len(supplied) != 3:
        raise ValueError(
            "Vertical datum requires authority, code, and name together "
            "(or none of them to declare the datum unknown).")
    if supplied:
        if note is not None:
            raise ValueError(
                "A datum note is only valid with an unknown datum; the "
                "known-datum shape has no note field.")
        if code < 1:
            raise ValueError(
                "Vertical datum code must be a positive integer.")
        return {"status": "known", "authority": authority,
                "code": code, "name": name}
    datum = {"status": "unknown"}
    if note is not None:
        datum["note"] = note
    return datum


def _declared_epsg(crs_candidates, source):
    for candidate in crs_candidates:
        if candidate.startswith("EPSG:"):
            return int(candidate.split(":", 1)[1])
    raise ValueError(
        f"{source} declares no EPSG horizontal CRS; the handoff contract "
        "requires one and never infers it.")
