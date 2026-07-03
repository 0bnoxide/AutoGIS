"""Tests for autogis/core/envmon/boring_log_report.py (tool 8.0c)."""
import sqlite3
from datetime import datetime

from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.qa import QACollector, SEV_WARNING
from autogis.core.common.schema.boring import (
    BoringLocation, BoringPhoto, BoringSample, GroundwaterObservation,
    LithologyInterval, WellConstruction,
)
from autogis.core.common.sqlite_schema import insert_rows
from autogis.core.envmon.boring_log_report import (
    build_appendix, build_boring_log, read_boring_records, write_outputs,
)
from autogis.core.envmon.create_boring_log_database import (
    create_boring_log_database,
)

LOCATION = BoringLocation(
    boring_id="B-1", site_id="H281", location_type="boring",
    northing=100.0, easting=200.0, ground_elevation=12.5,
    toc_elevation=None, status="logged", coordinate_system="MT SP",
    vertical_datum="NAVD88", driller="ACME Drilling",
    logged_by="J. Geologist", total_depth_ft=20.0,
    completion_type="monitoring well",
).to_row()

# Deliberately unsorted: 5-12 before 0-5.
LITHOLOGY = [
    LithologyInterval(boring_id="B-1", top_depth=5.0, bottom_depth=12.0,
                      uscs="CL", primary_material="clay", color="gray",
                      moisture="moist", pid_ppm=3.2,
                      description="lean clay").to_row(),
    LithologyInterval(boring_id="B-1", top_depth=0.0, bottom_depth=5.0,
                      uscs="SM", primary_material="silty sand",
                      color="brown", moisture="dry",
                      description="silty sand fill").to_row(),
]

SAMPLES = [
    BoringSample(sample_id="S-1", boring_id="B-1", sample_type="grab",
                 top_depth=6.0, bottom_depth=8.0, recovery=18.0,
                 blow_counts="4-6-8", lab_submitted=True, matrix="soil",
                 analytical_group="VOC").to_row(),
]

CONSTRUCTION = [
    WellConstruction(boring_id="B-1", component_type="screen",
                     top_depth=10.0, bottom_depth=20.0, diameter=2.0,
                     material="PVC", slot_size="0.010").to_row(),
    WellConstruction(boring_id="B-1", component_type="riser",
                     top_depth=0.0, bottom_depth=10.0, diameter=2.0,
                     material="PVC").to_row(),
]

GROUNDWATER = [
    GroundwaterObservation(boring_id="B-1",
                           observation_datetime=datetime(2026, 6, 1, 14, 30),
                           depth_to_water=8.5,
                           observation_type="during drilling").to_row(),
]

PHOTOS = [
    BoringPhoto(photo_id="P-1", boring_id="B-1", depth=5.0,
                photo_path="photos/p1.jpg", caption="core box 1",
                taken_by="JG").to_row(),
]


def _doc(**over):
    kw = dict(location=LOCATION, lithology=LITHOLOGY, samples=SAMPLES,
              construction=CONSTRUCTION, groundwater=GROUNDWATER,
              photos=PHOTOS)
    kw.update(over)
    return build_boring_log("B-1", **kw)


# ---- build_boring_log -------------------------------------------------------

def test_header_and_approval_sections():
    md = _doc().markdown
    assert "# Boring Log — B-1" in md
    assert "## Header" in md
    assert "| Site | H281 |" in md
    assert "| Driller | ACME Drilling |" in md
    assert "| Logged by | J. Geologist |" in md
    assert "## Approval" in md
    assert "| Reviewed by |" in md


def test_lithology_renders_in_depth_order():
    md = _doc().markdown
    lith = md[md.index("## Lithologic Column"):md.index("## Samples")]
    assert lith.index("| 0.0 | 5.0 | SM |") < lith.index("| 5.0 | 12.0 | CL |")


def test_samples_and_pid_in_sample_table():
    md = _doc().markdown
    row = next(ln for ln in md.splitlines() if ln.startswith("| S-1 |"))
    assert "| 6.0 | 8.0 |" in row
    assert "4-6-8" in row
    assert "3.2" in row       # PID from the overlapping 5-12 ft CL interval
    assert "| Y |" in row     # lab_submitted


def test_construction_renders_as_depth_indexed_table():
    md = _doc().markdown
    section = md[md.index("## Well Construction"):
                 md.index("## Groundwater Observations")]
    assert "| 0.0 | 10.0 | riser |" in section
    assert "| 10.0 | 20.0 | screen |" in section
    assert section.index("riser") < section.index("screen")
    assert "0.010" in section


def test_no_samples_still_renders_with_warning():
    qa = QACollector()
    doc = _doc(samples=[], qa=qa)
    assert "_No samples recorded._" in doc.markdown
    assert doc.sample_rows == []
    assert any(r.severity == SEV_WARNING and r.category == "no_samples"
               for r in qa.records)


# ---- build_appendix / write_outputs -----------------------------------------

def _two_docs():
    d1 = _doc()
    loc2 = dict(LOCATION, boring_id="B-2")
    d2 = build_boring_log("B-2", location=loc2, lithology=[], samples=[],
                          construction=[], groundwater=[], photos=[])
    return [d1, d2]


def test_appendix_lists_every_boring_in_contents():
    appendix = build_appendix(_two_docs())
    contents = appendix[:appendix.index("---")]
    assert "- B-1" in contents
    assert "- B-2" in contents
    assert "# Boring Log — B-1" in appendix
    assert "# Boring Log — B-2" in appendix


def test_write_outputs_produces_all_files(tmp_path):
    paths = write_outputs(_two_docs(), tmp_path / "logs")
    names = {p.name for p in paths}
    assert names == {"boring_log_B-1.md", "boring_log_B-2.md",
                     "appendix.md", "photo_log.md", "sample_summary.csv"}
    assert all(p.exists() for p in paths)
    csv_text = (tmp_path / "logs" / "sample_summary.csv").read_text()
    assert "boring_id,sample_id" in csv_text
    assert "B-1,S-1" in csv_text
    assert "core box 1" in (tmp_path / "logs" / "photo_log.md").read_text(
        encoding="utf-8")


# ---- read_boring_records (the read API 8.0a never shipped) ------------------

def _seed_db(tmp_path):
    db = tmp_path / "borings.sqlite"
    create_boring_log_database(db)
    conn = sqlite3.connect(str(db))
    try:
        insert_rows(conn, BoringLocation, [LOCATION,
                                           dict(LOCATION, boring_id="B-2")])
        insert_rows(conn, LithologyInterval, LITHOLOGY)
        insert_rows(conn, BoringSample, SAMPLES)
        insert_rows(conn, WellConstruction, CONSTRUCTION)
        insert_rows(conn, GroundwaterObservation, GROUNDWATER)
        insert_rows(conn, BoringPhoto, PHOTOS)
        conn.commit()
    finally:
        conn.close()
    return db


def test_read_boring_records_bundles_match_build_kwargs(tmp_path):
    db = _seed_db(tmp_path)
    bundles = read_boring_records(db)
    assert set(bundles) == {"B-1", "B-2"}
    b1 = bundles["B-1"]
    assert set(b1) == {"location", "lithology", "samples", "construction",
                       "groundwater", "photos"}
    assert b1["location"]["site_id"] == "H281"
    assert len(b1["lithology"]) == 2
    assert b1["samples"][0]["sample_id"] == "S-1"
    assert bundles["B-2"]["lithology"] == []
    # bundle feeds build_boring_log directly
    doc = build_boring_log("B-1", **b1)
    assert "# Boring Log — B-1" in doc.markdown


def test_read_boring_records_filter_warns_on_unknown_id(tmp_path):
    db = _seed_db(tmp_path)
    qa = QACollector()
    bundles = read_boring_records(db, boring_ids=["B-1", "B-99"], qa=qa)
    assert set(bundles) == {"B-1"}
    assert any(r.category == "boring_not_found" for r in qa.records)


# ---- CLI wiring --------------------------------------------------------------

def test_gen_boring_logs_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "gen-boring-logs" in result.output


def test_cli_gen_boring_logs_end_to_end(tmp_path):
    db = _seed_db(tmp_path)
    out_dir = tmp_path / "boring_logs"
    result = CliRunner().invoke(autogis, [
        "envmon", "gen-boring-logs", "--db", str(db),
        "--out-dir", str(out_dir)])
    assert result.exit_code == 0, result.output
    assert (out_dir / "boring_log_B-1.md").exists()
    assert (out_dir / "appendix.md").exists()
    assert (out_dir / "photo_log.md").exists()
    assert (out_dir / "sample_summary.csv").exists()
    # B-2 has no samples -> WARNING surfaced but not fatal by default
    assert "no_samples" in result.output


def test_cli_gen_boring_logs_borings_filter(tmp_path):
    db = _seed_db(tmp_path)
    out_dir = tmp_path / "boring_logs"
    result = CliRunner().invoke(autogis, [
        "envmon", "gen-boring-logs", "--db", str(db),
        "--out-dir", str(out_dir), "--borings", "B-2"])
    assert result.exit_code == 0, result.output
    assert (out_dir / "boring_log_B-2.md").exists()
    assert not (out_dir / "boring_log_B-1.md").exists()


def test_cli_gen_boring_logs_no_match_fails(tmp_path):
    db = _seed_db(tmp_path)
    result = CliRunner().invoke(autogis, [
        "envmon", "gen-boring-logs", "--db", str(db),
        "--out-dir", str(tmp_path / "x"), "--borings", "B-99"])
    assert result.exit_code == 1
    assert "no_borings" in result.output
