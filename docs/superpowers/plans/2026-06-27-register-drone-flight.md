# RegisterDroneFlight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `RegisterDroneFlight` — parse a flight inventory YAML or CSV into
`DroneFlights` and write `DroneControlPoints` + `DroneCheckpoints` if checkpoint files
are provided. Headless parse layer + LOCAL GDB write.

**Architecture:**
- New: `autogis/core/envmon/register_drone_flight.py`
- Modify: `autogis/adapters/cli.py` — add `register-drone-flight` command (LOCAL)
- New: `tests/envmon/test_register_drone_flight.py`
- New: `autogis/config/drone_flights/flight.example.yaml`

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- YAML/CSV parse is arcpy-free. GDB write is LOCAL.
- Run tests with `python -m pytest -q`.

---

### Task 1: `register_drone_flight.py` + tests

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_register_drone_flight.py`:

```python
import yaml
from pathlib import Path
from autogis.core.envmon.register_drone_flight import (
    DroneFlightRecord, load_flight_yaml, validate_flight_record,
)
from autogis.core.common.qa import QACollector

_YAML = """\
flight_id: "H281-2026-F01"
project_id: "H281"
site_id: "H281"
flight_date: "2026-06-14"
pilot: "Alice Smith"
drone_model: "DJI Phantom 4 RTK"
sensor: "RGB"
flight_altitude_m: 60.0
overlap_forward_pct: 80
overlap_side_pct: 70
gcp_used: true
checkpoint_count: 5
processing_software: "Agisoft Metashape"
output_crs: "EPSG:26917"
vertical_datum: "NAVD88"
orthomosaic_path: "C:/data/H281_ortho.tif"
dsm_path: "C:/data/H281_DSM.tif"
qa_status: "PASS"
"""


def test_load_flight_yaml(tmp_path):
    p = tmp_path / "flight.yaml"
    p.write_text(_YAML, encoding="utf-8")
    rec = load_flight_yaml(p)
    assert rec.flight_id == "H281-2026-F01"
    assert rec.gcp_used is True
    assert rec.checkpoint_count == 5


def test_validate_flight_required_fields(tmp_path):
    p = tmp_path / "flight.yaml"
    p.write_text(_YAML, encoding="utf-8")
    rec = load_flight_yaml(p)
    qa = QACollector()
    validate_flight_record(rec, qa)
    assert qa.counts_by_severity().get("ERROR", 0) == 0


def test_validate_flight_missing_pilot(tmp_path):
    data = yaml.safe_load(_YAML)
    data.pop("pilot")
    p = tmp_path / "flight.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    rec = load_flight_yaml(p)
    qa = QACollector()
    validate_flight_record(rec, qa)
    assert any(r.category == "missing_required_field" for r in qa.records)


def test_validate_flight_negative_altitude(tmp_path):
    data = yaml.safe_load(_YAML)
    data["flight_altitude_m"] = -10.0
    p = tmp_path / "flight.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    rec = load_flight_yaml(p)
    qa = QACollector()
    validate_flight_record(rec, qa)
    assert any(r.category == "invalid_altitude" for r in qa.records)


def test_load_flight_yaml_defaults(tmp_path):
    minimal = "flight_id: F01\nsite_id: H281\nflight_date: 2026-06-14\n"
    p = tmp_path / "f.yaml"
    p.write_text(minimal, encoding="utf-8")
    rec = load_flight_yaml(p)
    assert rec.gcp_used is False
    assert rec.checkpoint_count == 0
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_register_drone_flight.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/register_drone_flight.py`**

```python
"""register_drone_flight.py — drone flight inventory YAML → GDB write (LOCAL)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..common.config import load_config
from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_WARNING


@dataclass
class DroneFlightRecord:
    flight_id: str
    site_id: str
    flight_date: str
    project_id: str = ""
    pilot: str = ""
    drone_model: str = ""
    sensor: str = ""
    flight_altitude_m: Optional[float] = None
    overlap_forward_pct: Optional[float] = None
    overlap_side_pct: Optional[float] = None
    gcp_used: bool = False
    checkpoint_count: int = 0
    processing_software: str = ""
    output_crs: str = ""
    vertical_datum: str = ""
    orthomosaic_path: str = ""
    dsm_path: str = ""
    dem_path: str = ""
    point_cloud_path: str = ""
    qa_status: str = "PENDING"


def load_flight_yaml(path: Path) -> DroneFlightRecord:
    data = load_config(path)
    return DroneFlightRecord(
        flight_id=str(data.get("flight_id", "")),
        site_id=str(data.get("site_id", "")),
        flight_date=str(data.get("flight_date", "")),
        project_id=str(data.get("project_id", "")),
        pilot=str(data.get("pilot", "")),
        drone_model=str(data.get("drone_model", "")),
        sensor=str(data.get("sensor", "")),
        flight_altitude_m=float(data["flight_altitude_m"]) if data.get("flight_altitude_m") is not None else None,
        overlap_forward_pct=float(data["overlap_forward_pct"]) if data.get("overlap_forward_pct") is not None else None,
        overlap_side_pct=float(data["overlap_side_pct"]) if data.get("overlap_side_pct") is not None else None,
        gcp_used=bool(data.get("gcp_used", False)),
        checkpoint_count=int(data.get("checkpoint_count", 0)),
        processing_software=str(data.get("processing_software", "")),
        output_crs=str(data.get("output_crs", "")),
        vertical_datum=str(data.get("vertical_datum", "")),
        orthomosaic_path=str(data.get("orthomosaic_path", "")),
        dsm_path=str(data.get("dsm_path", "")),
        dem_path=str(data.get("dem_path", "")),
        point_cloud_path=str(data.get("point_cloud_path", "")),
        qa_status=str(data.get("qa_status", "PENDING")),
    )


def validate_flight_record(rec: DroneFlightRecord, qa: QACollector) -> None:
    for f_name in ("pilot", "drone_model", "sensor"):
        if not getattr(rec, f_name):
            qa.add(QARecord(SEV_ERROR, "missing_required_field",
                            f"DroneFlightRecord missing {f_name!r}"))
    if rec.flight_altitude_m is not None and rec.flight_altitude_m <= 0:
        qa.add(QARecord(SEV_ERROR, "invalid_altitude",
                        f"flight_altitude_m must be positive, got {rec.flight_altitude_m}"))


def write_drone_flight(   # pragma: no cover
    gdb_path: str,
    rec: DroneFlightRecord,
) -> None:
    import arcpy
    from datetime import datetime
    from pathlib import Path as _P
    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    table = str(_P(gdb_path) / "DroneFlights")
    if not _ax.Exists(table):
        return
    with _ax.da.InsertCursor(table,
                             ["FlightID", "ProjectID", "SiteID", "FlightDate",
                              "Pilot", "DroneModel", "Sensor",
                              "FlightAltitude_m", "OverlapForward_pct",
                              "OverlapSide_pct", "GCPUsed", "CheckpointCount",
                              "ProcessingSoftware", "OutputCRS", "VerticalDatum",
                              "OrthomosaicPath", "DSMPath", "DEMPath",
                              "PointCloudPath", "QAStatus"]) as cur:
        try:
            fd = datetime.strptime(rec.flight_date, "%Y-%m-%d")
        except ValueError:
            fd = None
        cur.insertRow([rec.flight_id, rec.project_id, rec.site_id, fd,
                       rec.pilot, rec.drone_model, rec.sensor,
                       rec.flight_altitude_m, rec.overlap_forward_pct,
                       rec.overlap_side_pct, int(rec.gcp_used), rec.checkpoint_count,
                       rec.processing_software, rec.output_crs, rec.vertical_datum,
                       rec.orthomosaic_path, rec.dsm_path, rec.dem_path,
                       rec.point_cloud_path, rec.qa_status])
```

- [ ] **Step 4: Create example YAML**

```yaml
# autogis/config/drone_flights/flight.example.yaml
flight_id: "H281-2026-F01"
project_id: "H281"
site_id: "H281"
flight_date: "2026-06-14"
pilot: "Alice Smith"
drone_model: "DJI Phantom 4 RTK"
sensor: "RGB"
flight_altitude_m: 60.0
overlap_forward_pct: 80
overlap_side_pct: 70
gcp_used: true
checkpoint_count: 5
processing_software: "Agisoft Metashape 2.0"
output_crs: "EPSG:26917"
vertical_datum: "NAVD88"
orthomosaic_path: "C:/GIS/H281/drone/H281_2026_ortho.tif"
dsm_path: "C:/GIS/H281/drone/H281_2026_DSM.tif"
qa_status: "PASS"
```

- [ ] **Step 5: Run tests + full suite + commit**

```bash
git add autogis/core/envmon/register_drone_flight.py \
        autogis/config/drone_flights/flight.example.yaml \
        tests/envmon/test_register_drone_flight.py
git commit -m "feat(envmon): register_drone_flight — DroneFlightRecord + YAML loader + GDB write"
```

---

### Task 2: CLI command `register-drone-flight`

```python
@envmon.command("register-drone-flight")
@click.argument("flight_yaml", type=click.Path(exists=True))
@click.option("--gdb", required=True, type=click.Path())
@click.option("--dry-run", is_flag=True, default=False)
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def register_drone_flight_cmd(flight_yaml, gdb, dry_run, report, fail_on):
    """Register a drone flight record in the GDB (ArcGIS Pro)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.register_drone_flight import (
        load_flight_yaml, validate_flight_record, write_drone_flight)
    rec = load_flight_yaml(Path(flight_yaml))
    qa = QACollector()
    validate_flight_record(rec, qa)
    if not dry_run and qa.counts_by_severity().get("ERROR", 0) == 0:
        _guard("register-drone-flight")
        write_drone_flight(gdb, rec)
        click.echo(f"Flight {rec.flight_id} registered in {gdb}.")
    _render_qa(qa, report, fail_on)
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_register_drone_flight.py
git commit -m "feat(cli): add register-drone-flight command (LOCAL, dry-run supported)"
```
