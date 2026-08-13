# `autogis handoff` — Contract-v1 Package Emitter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement ADR-0128 — a headless `autogis handoff` command that emits AutoGIS-Civil3D contract-v1 package ZIPs through the production LandXML writer, with never-inferred metadata.

**Architecture:** One arcpy-free core module (`autogis/core/handoff.py`) builds the package: parse the source LandXML, re-emit the surface via `write_landxml_surface`, hash it, assemble the manifest as a plain dict, zip exactly two entries. The CLI is a thin Click adapter. A shared source-metadata reader is promoted from `landxml_transform` into `core/common/landxml.py` first so both consumers use one extraction path.

**Tech Stack:** Python stdlib (`zipfile`, `json`, `uuid`, `datetime`, `tempfile`), existing core (`parse_landxml_surface`, `write_landxml_surface`, `parse_epsg`, `compute_sha256`), Click, pytest.

## Global Constraints

- Spec: `docs/adr/0128-civil3d-handoff-package-emitter.md` (Accepted via AutoGIS PR #478). Its manifest/flag rules are binding, verbatim.
- Work happens in the worktree `C:\Users\ichbi\AutoGIS\.claude\worktrees\handoff-emitter` on branch `claude/handoff-emitter`; run every command from that root.
- Arcpy-free, base-install only: **no new dependencies, no new extras, no pyproj**. Everything must import with only `PyYAML, click, openpyxl, numpy, xlrd` installed.
- Contract exact values (never paraphrase): `contract_version` `"1.0"`; units exactly `metre` | `international_foot` | `us_survey_foot`; LandXML→manifest unit map `meter`→`metre`, `foot`→`international_foot`, `USSurveyFoot`→`us_survey_foot`; datum `{"status":"known", authority, code, name}` or `{"status":"unknown"[, note]}`; `direction` `"positive_up"`; `kind` `"projected"`; `authority` `"EPSG"`; `filename` `"surface.landxml"`; `landxml_version` `"1.2"`; `sha256` lowercase hex of the ZIP-entry bytes; `created_utc` UTC with trailing `Z`; `source_commit` matches `^[0-9a-f]{7,64}$`.
- Never infer: horizontal EPSG and linear unit come only from the source file's declared `CoordinateSystem`/`Units`; failures are loud `ValueError`s. No vendored schema, no self-validation.
- Tests: pytest, function style. Run as `python -m pytest <files> -q`. If `import autogis` fails, set `$env:PYTHONPATH = "C:\Users\ichbi\AutoGIS\.claude\worktrees\handoff-emitter"` first.
- Write all new files UTF-8. Commits: conventional style, trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Promote the source-metadata reader into `core/common/landxml.py`

**Files:**
- Modify: `autogis/core/common/landxml.py` (add `authority_crs`, `SourceMetadata`, `read_source_metadata`)
- Modify: `autogis/core/envmon/landxml_transform.py` (delete the private copies, import the public ones)
- Test: `tests/test_landxml.py` (append)

**Interfaces:**
- Consumes: existing `parse_epsg` in `landxml.py`; `NamedTuple` is already imported there (see `CgPoint`), as are `re`, `ET`, `Path`, `Optional`.
- Produces: `read_source_metadata(path: Path) -> SourceMetadata` where `SourceMetadata(crs: tuple[str, ...], linear_unit: str | None, elevation_unit: str | None, surface_names: tuple[str, ...])`, and `authority_crs(value: str | None) -> str | None`. Task 2 imports `read_source_metadata` from `autogis.core.common.landxml`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_landxml.py` (extend the existing import from `autogis.core.common.landxml` with `SourceMetadata, read_source_metadata`):

```python
_LANDXML_META = """<?xml version="1.0"?>
<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2">
  <Units>
    <Metric linearUnit="meter" elevationUnit="meter"/>
  </Units>
  <CoordinateSystem name="EPSG:26913" epsgCode="26913"/>
  <Surfaces>
    <Surface name="EG">
      <Definition surfType="TIN">
        <Pnts>
          <P id="1">0.0 0.0 100.0</P>
          <P id="2">0.0 10.0 102.0</P>
          <P id="3">10.0 0.0 98.0</P>
        </Pnts>
        <Faces>
          <F>1 2 3</F>
        </Faces>
      </Definition>
    </Surface>
  </Surfaces>
</LandXML>
"""


def test_read_source_metadata_declared_values(tmp_path):
    meta = read_source_metadata(_write(tmp_path, _LANDXML_META))
    assert meta.crs == ("EPSG:26913",)
    assert meta.linear_unit == "meter"
    assert meta.elevation_unit == "meter"
    assert meta.surface_names == ("EG",)


def test_read_source_metadata_absent_declarations(tmp_path):
    meta = read_source_metadata(_write(tmp_path))
    assert meta == SourceMetadata((), None, None, ("EG",))


def test_read_source_metadata_both_unit_systems_raise(tmp_path):
    text = _LANDXML_META.replace(
        "<Metric linearUnit=\"meter\" elevationUnit=\"meter\"/>",
        "<Metric linearUnit=\"meter\" elevationUnit=\"meter\"/>"
        "<Imperial linearUnit=\"foot\" elevationUnit=\"feet\"/>")
    with pytest.raises(ValueError, match="both Metric and Imperial"):
        read_source_metadata(_write(tmp_path, text))
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `python -m pytest tests/test_landxml.py -q`
Expected: ImportError/collection error — `SourceMetadata` not defined.

- [ ] **Step 3: Add the public API to `autogis/core/common/landxml.py`** — place after `linear_unit_scale` (around line 80), moving the regex + logic verbatim from `landxml_transform.py:19-20,42-86` and adding the `elevationUnit` read:

```python
_AUTHORITY_CRS_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9_-]*)\s*:\s*(\d+)\s*$")


def authority_crs(value: Optional[str]) -> Optional[str]:
    """Return a normalized authority code, treating bare numbers as EPSG."""
    if parse_epsg(value) is not None:
        return f"EPSG:{parse_epsg(value)}"
    match = _AUTHORITY_CRS_RE.match(value or "")
    if match is None:
        return None
    return f"{match.group(1).upper()}:{match.group(2)}"


class SourceMetadata(NamedTuple):
    """Metadata a LandXML file explicitly declares (never inferred)."""
    crs: tuple            # authority codes in declaration order
    linear_unit: Optional[str]     # Units linearUnit attribute, verbatim
    elevation_unit: Optional[str]  # Units elevationUnit attribute, verbatim
    surface_names: tuple


def read_source_metadata(path: Path) -> SourceMetadata:
    """Read the CRS, units, and surface names a LandXML file declares.

    Promoted from landxml_transform._source_metadata (ADR-0128) so the
    transform and handoff-packaging paths share one extraction.
    """
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"Malformed LandXML {path}: {exc}") from None
    coordinate_system = root.find(".//{*}CoordinateSystem")
    declared_crs = []
    if coordinate_system is not None:
        epsg = parse_epsg(coordinate_system.get("epsgCode"))
        if epsg is not None:
            declared_crs.append(f"EPSG:{epsg}")
        named = authority_crs(coordinate_system.get("name"))
        if named is not None and named not in declared_crs:
            declared_crs.append(named)

    unit_elements = [
        element for element in (
            root.find(".//{*}Units/{*}Metric"),
            root.find(".//{*}Units/{*}Imperial"),
        )
        if element is not None
    ]
    if len(unit_elements) > 1:
        raise ValueError(
            f"{path} declares both Metric and Imperial LandXML units.")
    declared_unit = (
        unit_elements[0].get("linearUnit") if unit_elements else None
    )
    elevation_unit = (
        unit_elements[0].get("elevationUnit") if unit_elements else None
    )
    surface_names = tuple(
        surface.get("name", "")
        for surface in root.findall(".//{*}Surfaces/{*}Surface")
    )
    return SourceMetadata(
        tuple(declared_crs), declared_unit, elevation_unit, surface_names)
```

If `landxml.py`'s ET import differs (check its header), match whatever alias it already uses.

- [ ] **Step 4: Point `landxml_transform.py` at the public API**

1. Delete `_AUTHORITY_CRS_RE` (lines 19-20), `_authority_crs` (42-49), and `_source_metadata` (52-86).
2. Extend the existing `from ..common.landxml import (...)` block with `authority_crs` and `read_source_metadata`.
3. In `_load_crs` (was lines 89-118) the local variable `authority_crs` would now shadow the import — rename it to `authority_code`:

```python
def _load_crs(crs_text: str, *, target: bool = False):
    try:
        from pyproj import CRS
    except ImportError:
        raise RuntimeError(
            "LandXML CRS transformation needs pyproj; install it with "
            "`pip install autogis[landxml]`.") from None

    authority_code = authority_crs(crs_text)
    if authority_code is None:
        raise ValueError(
            f"CRS {crs_text!r} must be an authority code such as EPSG:4326 "
            "or ESRI:102700.")
    if target and not authority_code.startswith("EPSG:"):
        raise ValueError(
            f"Target CRS {crs_text!r} must be an EPSG code so output "
            "LandXML metadata remains machine-readable.")
    try:
        crs = CRS.from_user_input(authority_code)
    except Exception as exc:
        raise ValueError(
            f"Unknown or invalid CRS {authority_code}: {exc}") from None
    if target and not crs.is_projected:
        raise ValueError(
            f"Target CRS {authority_code} must be projected; geographic "
            "degree coordinates cannot be written as LandXML feet/meters.")
    if not target and not (crs.is_projected or crs.is_geographic):
        raise ValueError(
            f"Source CRS {authority_code} must be geographic or projected.")
    return crs, authority_code
```

4. Update the single call site (was line 391) to the four-field tuple:

```python
    declared_crs, declared_unit, _, surface_names = read_source_metadata(
        source_path)
```

5. Grep the module and `tests/envmon/test_landxml_transform.py` for any other `_authority_crs` / `_source_metadata` references and update them the same way.

- [ ] **Step 5: Run the affected suites**

Run: `python -m pytest tests/test_landxml.py tests/envmon/test_landxml_transform.py tests/test_toolbox_cad.py -q`
Expected: all pass (transform tests may skip where pyproj is absent — skips are fine, failures are not).

- [ ] **Step 6: Commit**

```bash
git add autogis/core/common/landxml.py autogis/core/envmon/landxml_transform.py tests/test_landxml.py tests/envmon/test_landxml_transform.py
git commit -m "refactor(landxml): promote source-metadata reader to core/common (ADR-0128)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

(Only add the transform test file if Step 4.5 changed it.)

---

### Task 2: `autogis/core/handoff.py` + `__version__`

**Files:**
- Modify: `autogis/__init__.py` (currently empty)
- Create: `autogis/core/handoff.py`
- Test: `tests/test_handoff.py`

**Interfaces:**
- Consumes: `read_source_metadata` (Task 1), `parse_landxml_surface`, `write_landxml_surface` from `autogis.core.common.landxml`; `compute_sha256` from `autogis.core.envmon.source_registry`.
- Produces: `build_handoff_package(input_path, output_path, *, vertical_unit, surface_name="", datum_authority=None, datum_code=None, datum_name=None, datum_note=None, source_commit=None, overwrite=False) -> dict` (returns the manifest). Task 3's CLI calls exactly this. Raises `ValueError` for every rule violation and `FileExistsError` for an existing output without `overwrite`.

- [ ] **Step 1: Set the version constant** — replace the empty `autogis/__init__.py` with:

```python
"""AutoGIS — automation tools for ArcGIS Pro / ArcGIS Online."""
__version__ = "0.1.0"
```

(`0.1.0` must equal `[project] version` in `pyproject.toml` — check it at implementation time and use whatever it says then.)

- [ ] **Step 2: Write the failing tests** — create `tests/test_handoff.py`:

```python
"""Tests for autogis/core/handoff.py (ADR-0128 contract-v1 emitter)."""
import hashlib
import json
import tomllib
import uuid
import zipfile
from pathlib import Path

import pytest

from autogis import __version__
from autogis.core.handoff import build_handoff_package

_METRIC = """<?xml version="1.0"?>
<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2">
  <Units>
    <Metric linearUnit="meter" elevationUnit="meter"/>
  </Units>
  <CoordinateSystem name="EPSG:26913" epsgCode="26913"/>
  <Surfaces>
    <Surface name="Existing Ground">
      <Definition surfType="TIN">
        <Pnts>
          <P id="1">0.0 0.0 100.0</P>
          <P id="2">0.0 10.0 102.0</P>
          <P id="3">10.0 0.0 98.0</P>
        </Pnts>
        <Faces>
          <F>1 2 3</F>
        </Faces>
      </Definition>
    </Surface>
  </Surfaces>
</LandXML>
"""

_IMPERIAL = _METRIC.replace(
    '<Metric linearUnit="meter" elevationUnit="meter"/>',
    '<Imperial linearUnit="USSurveyFoot" elevationUnit="feet"/>').replace(
    'name="EPSG:26913" epsgCode="26913"', 'name="EPSG:2256" epsgCode="2256"')

KNOWN = dict(datum_authority="EPSG", datum_code=5703,
             datum_name="NAVD88 height")


def _source(tmp_path, text=_METRIC):
    p = tmp_path / "source.xml"
    p.write_text(text, encoding="utf-8")
    return p


def test_known_datum_manifest_and_zip(tmp_path):
    out = tmp_path / "pkg.zip"
    manifest = build_handoff_package(
        _source(tmp_path), out, vertical_unit="metre",
        source_commit="0123abc", **KNOWN)
    with zipfile.ZipFile(out) as zf:
        assert sorted(zf.namelist()) == ["handoff.json", "surface.landxml"]
        stored = json.loads(zf.read("handoff.json").decode("utf-8"))
        surface_bytes = zf.read("surface.landxml")
    assert stored == manifest
    assert manifest["contract_version"] == "1.0"
    uuid.UUID(manifest["package_id"])
    assert manifest["created_utc"].endswith("Z")
    assert manifest["producer"] == {
        "name": "AutoGIS", "version": __version__,
        "source_commit": "0123abc"}
    surface = manifest["surface"]
    assert surface["filename"] == "surface.landxml"
    assert surface["landxml_version"] == "1.2"
    assert surface["sha256"] == hashlib.sha256(surface_bytes).hexdigest()
    assert surface["name"] == "Existing Ground"
    assert surface["point_count"] == 3
    assert surface["face_count"] == 1
    ref = manifest["coordinate_reference"]
    assert ref["horizontal"] == {"kind": "projected", "authority": "EPSG",
                                 "code": 26913, "unit": "metre"}
    assert ref["vertical"] == {
        "unit": "metre", "direction": "positive_up",
        "datum": {"status": "known", "authority": "EPSG", "code": 5703,
                  "name": "NAVD88 height"}}
    assert b"<Pnts>" in surface_bytes  # re-emitted by the writer


def test_unknown_datum_with_note(tmp_path):
    manifest = build_handoff_package(
        _source(tmp_path), tmp_path / "pkg.zip", vertical_unit="metre",
        datum_note="Confirm project datum before import")
    assert manifest["coordinate_reference"]["vertical"]["datum"] == {
        "status": "unknown", "note": "Confirm project datum before import"}
    assert "source_commit" not in manifest["producer"]


def test_unknown_datum_without_note_has_no_note_key(tmp_path):
    manifest = build_handoff_package(
        _source(tmp_path), tmp_path / "pkg.zip", vertical_unit="metre")
    assert manifest["coordinate_reference"]["vertical"]["datum"] == {
        "status": "unknown"}


def test_partial_datum_trio_rejected(tmp_path):
    with pytest.raises(ValueError, match="authority, code, and name"):
        build_handoff_package(
            _source(tmp_path), tmp_path / "pkg.zip", vertical_unit="metre",
            datum_authority="EPSG", datum_code=5703)


def test_note_with_known_datum_rejected(tmp_path):
    with pytest.raises(ValueError, match="only valid with an unknown"):
        build_handoff_package(
            _source(tmp_path), tmp_path / "pkg.zip", vertical_unit="metre",
            datum_note="nope", **KNOWN)


def test_missing_epsg_rejected(tmp_path):
    text = _METRIC.replace(
        '  <CoordinateSystem name="EPSG:26913" epsgCode="26913"/>\n', "")
    with pytest.raises(ValueError, match="no EPSG horizontal CRS"):
        build_handoff_package(
            _source(tmp_path, text), tmp_path / "pkg.zip",
            vertical_unit="metre")


def test_missing_units_rejected(tmp_path):
    text = _METRIC.replace(
        '  <Units>\n    <Metric linearUnit="meter" elevationUnit="meter"/>\n'
        '  </Units>\n', "")
    with pytest.raises(ValueError, match="no supported LandXML linearUnit"):
        build_handoff_package(
            _source(tmp_path, text), tmp_path / "pkg.zip",
            vertical_unit="metre")


def test_metric_source_rejects_foot_vertical(tmp_path):
    with pytest.raises(ValueError, match="elevation family"):
        build_handoff_package(
            _source(tmp_path), tmp_path / "pkg.zip",
            vertical_unit="international_foot")


def test_imperial_source_takes_either_foot_and_rejects_metre(tmp_path):
    manifest = build_handoff_package(
        _source(tmp_path, _IMPERIAL), tmp_path / "a.zip",
        vertical_unit="us_survey_foot")
    ref = manifest["coordinate_reference"]
    assert ref["horizontal"]["unit"] == "us_survey_foot"
    assert ref["horizontal"]["code"] == 2256
    assert ref["vertical"]["unit"] == "us_survey_foot"
    with pytest.raises(ValueError, match="elevation family"):
        build_handoff_package(
            _source(tmp_path, _IMPERIAL), tmp_path / "b.zip",
            vertical_unit="metre")


def test_contradictory_elevation_unit_rejected(tmp_path):
    text = _IMPERIAL.replace('elevationUnit="feet"', 'elevationUnit="meter"')
    with pytest.raises(ValueError, match="refusing to alter"):
        build_handoff_package(
            _source(tmp_path, text), tmp_path / "pkg.zip",
            vertical_unit="us_survey_foot")


def test_identical_input_output_rejected_even_with_overwrite(tmp_path):
    src = _source(tmp_path)
    with pytest.raises(ValueError, match="must be different"):
        build_handoff_package(
            src, src, vertical_unit="metre", overwrite=True)


def test_existing_output_needs_overwrite(tmp_path):
    out = tmp_path / "pkg.zip"
    out.write_bytes(b"old")
    with pytest.raises(FileExistsError):
        build_handoff_package(_source(tmp_path), out, vertical_unit="metre")
    build_handoff_package(
        _source(tmp_path), out, vertical_unit="metre", overwrite=True)
    assert zipfile.is_zipfile(out)


def test_bad_source_commit_rejected(tmp_path):
    with pytest.raises(ValueError, match="lowercase hex"):
        build_handoff_package(
            _source(tmp_path), tmp_path / "pkg.zip", vertical_unit="metre",
            source_commit="ABCDEF1")


def test_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject.open("rb") as fh:
        assert tomllib.load(fh)["project"]["version"] == __version__
```

- [ ] **Step 3: Run to confirm failure**

Run: `python -m pytest tests/test_handoff.py -q`
Expected: collection error — `autogis.core.handoff` does not exist.

- [ ] **Step 4: Create `autogis/core/handoff.py`**

```python
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
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_handoff.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add autogis/__init__.py autogis/core/handoff.py tests/test_handoff.py
git commit -m "feat(handoff): contract-v1 package builder + __version__ (ADR-0128)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `autogis handoff` CLI command

**Files:**
- Modify: `autogis/adapters/cli.py` (add one top-level command; put it right after `harvest_cmd`, before the `envmon` group)
- Test: `tests/test_cli_handoff.py`

**Interfaces:**
- Consumes: `build_handoff_package` from Task 2 (lazy-imported inside the command, matching the house pattern).
- Produces: the `autogis handoff` command exactly as ADR-0128 specifies. The consumer repo's compat harness will invoke it as `python -m autogis handoff --input ... --output ... --vertical-unit ... --vertical-datum-* ... --source-commit ...`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_cli_handoff.py` (before writing, skim the top of `tests/test_cli.py` and copy any fixture/env setup it uses around `CliRunner` — run-history recording is already handled there; mirror it):

```python
"""CLI tests for `autogis handoff` (ADR-0128)."""
import json
import zipfile

from click.testing import CliRunner

from autogis.adapters.cli import autogis

_METRIC = """<?xml version="1.0"?>
<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2">
  <Units>
    <Metric linearUnit="meter" elevationUnit="meter"/>
  </Units>
  <CoordinateSystem name="EPSG:26913" epsgCode="26913"/>
  <Surfaces>
    <Surface name="Existing Ground">
      <Definition surfType="TIN">
        <Pnts>
          <P id="1">0.0 0.0 100.0</P>
          <P id="2">0.0 10.0 102.0</P>
          <P id="3">10.0 0.0 98.0</P>
        </Pnts>
        <Faces>
          <F>1 2 3</F>
        </Faces>
      </Definition>
    </Surface>
  </Surfaces>
</LandXML>
"""


def _write_source(tmp_path):
    p = tmp_path / "source.xml"
    p.write_text(_METRIC, encoding="utf-8")
    return p


def test_handoff_known_datum_succeeds(tmp_path):
    out = tmp_path / "pkg.zip"
    result = CliRunner().invoke(autogis, [
        "handoff",
        "--input", str(_write_source(tmp_path)),
        "--output", str(out),
        "--vertical-unit", "metre",
        "--vertical-datum-authority", "EPSG",
        "--vertical-datum-code", "5703",
        "--vertical-datum-name", "NAVD88 height",
        "--source-commit", "0123abc",
    ])
    assert result.exit_code == 0, result.output
    assert "handoff package ->" in result.output
    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read("handoff.json").decode("utf-8"))
    assert manifest["coordinate_reference"]["vertical"]["datum"][
        "status"] == "known"


def test_handoff_partial_datum_trio_fails(tmp_path):
    result = CliRunner().invoke(autogis, [
        "handoff",
        "--input", str(_write_source(tmp_path)),
        "--output", str(tmp_path / "pkg.zip"),
        "--vertical-unit", "metre",
        "--vertical-datum-authority", "EPSG",
    ])
    assert result.exit_code != 0
    assert "authority, code, and name" in result.output


def test_handoff_vertical_family_mismatch_fails(tmp_path):
    result = CliRunner().invoke(autogis, [
        "handoff",
        "--input", str(_write_source(tmp_path)),
        "--output", str(tmp_path / "pkg.zip"),
        "--vertical-unit", "international_foot",
    ])
    assert result.exit_code != 0
    assert "elevation family" in result.output
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_cli_handoff.py -q`
Expected: FAIL — `No such command 'handoff'`.

- [ ] **Step 3: Add the command to `autogis/adapters/cli.py`** — insert after `harvest_cmd` (around line 297):

```python
@autogis.command("handoff")
@click.option("--input", "input_path", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Source LandXML file containing the TIN surface.")
@click.option("--output", "output_path", required=True,
              type=click.Path(dir_okay=False),
              help="Contract-v1 package ZIP to write.")
@click.option("--surface-name", default="",
              help="Surface to package when the source declares several; "
                   "default is the first surface.")
@click.option("--vertical-unit", required=True,
              type=click.Choice(
                  ["metre", "international_foot", "us_survey_foot"]),
              help="Manifest vertical unit; always explicit, checked "
                   "against the surface's elevation-unit family "
                   "(ADR-0128, never inferred).")
@click.option("--vertical-datum-authority", default=None,
              help="Vertical datum authority; with code and name this "
                   "declares a known datum.")
@click.option("--vertical-datum-code", type=int, default=None,
              help="Vertical datum authority code (positive integer).")
@click.option("--vertical-datum-name", default=None,
              help="Vertical datum name, e.g. 'NAVD88 height'.")
@click.option("--vertical-datum-note", default=None,
              help="Optional note recorded with an unknown datum only.")
@click.option("--source-commit", default=None,
              help="Producing commit (7-64 lowercase hex), recorded "
                   "verbatim in the manifest.")
@click.option("--overwrite", is_flag=True, default=False,
              help="Replace an existing output package.")
def handoff_cmd(input_path, output_path, surface_name, vertical_unit,
                vertical_datum_authority, vertical_datum_code,
                vertical_datum_name, vertical_datum_note, source_commit,
                overwrite):
    """Emit a contract-v1 Civil 3D handoff package ZIP (ADR-0128)."""
    from autogis.core.handoff import build_handoff_package
    try:
        manifest = build_handoff_package(
            input_path, output_path,
            vertical_unit=vertical_unit,
            surface_name=surface_name,
            datum_authority=vertical_datum_authority,
            datum_code=vertical_datum_code,
            datum_name=vertical_datum_name,
            datum_note=vertical_datum_note,
            source_commit=source_commit,
            overwrite=overwrite)
    except (ValueError, FileExistsError) as exc:
        raise click.ClickException(str(exc)) from exc
    surface = manifest["surface"]
    datum = manifest["coordinate_reference"]["vertical"]["datum"]
    click.echo(
        f"handoff package -> {output_path} "
        f"({surface['point_count']} points, {surface['face_count']} faces, "
        f"datum {datum['status']})")
```

- [ ] **Step 4: Run the CLI tests plus the CLI regression suites**

Run: `python -m pytest tests/test_cli_handoff.py tests/test_cli.py -q`
Expected: all pass. (`test_cli.py` guards the list-tools/GUI-introspection registries — if it fails on the new command, follow whatever its assertion says the registry needs; ADR-0092's drift guards may require the command be added to a discovery table. Fix per the failing assertion, never by skipping the test.)

- [ ] **Step 5: Smoke the real entry point**

Run: `python -m autogis handoff --help` (from the worktree root, `$env:PYTHONPATH` set if needed)
Expected: help text listing every flag above, exit 0.

- [ ] **Step 6: Commit**

```bash
git add autogis/adapters/cli.py tests/test_cli_handoff.py
git commit -m "feat(cli): autogis handoff command (ADR-0128)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

(Include any registry file Step 4 forced you to touch.)

---

### Task 4: Ship

**Files:** none beyond bookkeeping (plan file already committed by the controller).

**Interfaces:**
- Consumes: Tasks 1-3 committed on `claude/handoff-emitter`.
- Produces: green full suite; a PR in `0bnoxide/AutoGIS` with the five failure-mode probes classified (behavioral PR — see `docs/pr-review-failure-mode-audit.md`); a comment on AutoGIS-Civil3D gate issue #78 linking the PR.

- [ ] **Step 1:** Run the full arcpy-free suite: `python -m pytest -q` from the worktree root. Expected: pass (pre-existing skips fine).
- [ ] **Step 2:** Push and open the PR titled `feat(handoff): autogis handoff — contract-v1 package emitter (ADR-0128)`; body classifies BOUNDARY_SHAPE, CONTRACT_REACHABILITY, IDENTITY_PROVENANCE, SIDE_EFFECT_SAFETY, ENVIRONMENT_SEAM per `docs/pr-review-failure-mode-audit.md`, links ADR-0128 and AutoGIS-Civil3D#78.
- [ ] **Step 3:** Confirm AutoGIS CI (`pytest` on windows-2022) is green on the PR.
- [ ] **Step 4:** Comment on AutoGIS-Civil3D#78: feature PR open under ADR-0128, link both.
