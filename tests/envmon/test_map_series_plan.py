"""Tests for map_series_plan (Tool 5.6) — arcpy-free planner + gen-map-series CLI.

Planner tests exercise the four packet modes, deterministic/unique naming and
out_format propagation per the spec's Test Strategy
(docs/superpowers/specs/2026-06-28-generate-site-map-series-design.md).
CLI tests cover the headless --dry-run path and the clean guard error on the
arcpy export path (same pattern as test_cli_survey_to_well_elevation).
"""
import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.envmon.map_series_plan import MapJob, plan_map_series

SITES = ["SITE-A", "SITE-B"]
EVENTS = ["2026Q1", "2026Q2"]
SPECS = ["GW_FIG1", "SOIL_FIG2"]


# --- planner: modes ---

def test_per_site_one_job_per_site_spec_for_event():
    jobs = plan_map_series(SITES, ["2026Q2"], SPECS, mode="per_site")
    assert len(jobs) == 4  # 2 sites x 1 event x 2 specs
    # grouped by site: first two jobs are SITE-A's packet
    assert [j.site_id for j in jobs] == ["SITE-A", "SITE-A", "SITE-B", "SITE-B"]
    assert all(isinstance(j, MapJob) for j in jobs)


def test_per_map_type_groups_by_figure_spec_across_sites():
    jobs = plan_map_series(SITES, EVENTS, SPECS, mode="per_map_type")
    assert len(jobs) == 8
    # grouped by spec: first four jobs are all GW_FIG1 (2 sites x 2 events)
    assert [j.figure_spec for j in jobs[:4]] == ["GW_FIG1"] * 4
    assert [j.figure_spec for j in jobs[4:]] == ["SOIL_FIG2"] * 4


def test_combined_appendix_single_ordered_sequence():
    jobs = plan_map_series(SITES, ["2026Q2"], SPECS, mode="combined_appendix")
    assert [j.out_name.split("_")[1] for j in jobs] == ["001", "002", "003", "004"]
    assert all(j.out_name.startswith("Appendix_") for j in jobs)


def test_historical_groups_by_event_in_input_order():
    jobs = plan_map_series(["SITE-A"], EVENTS, ["GW_FIG1"], mode="historical")
    assert [j.event for j in jobs] == ["2026Q1", "2026Q2"]
    jobs = plan_map_series(SITES, EVENTS, SPECS, mode="historical")
    assert [j.event for j in jobs[:4]] == ["2026Q1"] * 4


# --- planner: naming, format, validation ---

def test_names_deterministic_and_unique_across_matrix():
    for mode in ("per_site", "per_map_type", "combined_appendix", "historical"):
        a = plan_map_series(SITES, EVENTS, SPECS, mode=mode)
        b = plan_map_series(SITES, EVENTS, SPECS, mode=mode)
        assert a == b, mode
        names = [j.out_name for j in a]
        assert len(names) == len(set(names)) == 8, mode


def test_out_format_propagates():
    jobs = plan_map_series(SITES, ["2026Q2"], SPECS, out_format="png")
    assert all(j.out_format == "png" for j in jobs)
    assert all(j.out_name.endswith(".png") for j in jobs)
    jobs = plan_map_series(SITES, ["2026Q2"], SPECS)
    assert all(j.out_name.endswith(".pdf") for j in jobs)


def test_duplicate_inputs_deduped():
    jobs = plan_map_series(["SITE-A", "SITE-A"], ["2026Q2"], ["GW_FIG1"])
    assert len(jobs) == 1


def test_unsafe_ids_sanitized_in_out_name():
    jobs = plan_map_series(["SITE A/1"], ["2026 Q2"], ["GW FIG"])
    assert jobs[0].out_name == "SITE_A_1_2026_Q2_GW_FIG.pdf"


def test_invalid_mode_and_format_raise():
    with pytest.raises(ValueError, match="mode"):
        plan_map_series(SITES, EVENTS, SPECS, mode="nope")
    with pytest.raises(ValueError, match="out_format"):
        plan_map_series(SITES, EVENTS, SPECS, out_format="docx")


def test_empty_inputs_yield_empty_plan():
    assert plan_map_series([], EVENTS, SPECS) == []


# --- CLI: gen-map-series ---

_SPEC_YAML = """\
figure_spec_id: GW_FIG1
site_id: SITE-A
map_type: GW_ANALYTICAL
matrix: GW
layout_name: Layout1
figure_title: GW Analytical
output_filename_pattern: "{site_id}_{figure_number}_{event_date}"
callout_template:
  template_id: CKG_GW
template_aprx: template.aprx
"""


def _spec_dir(tmp_path):
    d = tmp_path / "specs"
    d.mkdir()
    (d / "gw_fig1.yaml").write_text(_SPEC_YAML, encoding="utf-8")
    return d


def test_gen_map_series_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "gen-map-series" in result.output


def test_dry_run_is_headless(tmp_path):
    result = CliRunner().invoke(autogis, [
        "envmon", "gen-map-series",
        "--sites", "SITE-A,SITE-B", "--events", "2026Q2",
        "--specs", str(_spec_dir(tmp_path)), "--dry-run",
    ])
    assert result.exit_code == 0, result.output
    assert "2 map job" in result.output
    assert "SITE-A_2026Q2_GW_FIG1.pdf" in result.output


def test_dry_run_reads_site_and_event_files(tmp_path):
    sites = tmp_path / "sites.txt"
    sites.write_text("SITE-A\nSITE-B\n", encoding="utf-8")
    events = tmp_path / "events.txt"
    events.write_text("2026Q1\n2026Q2\n", encoding="utf-8")
    result = CliRunner().invoke(autogis, [
        "envmon", "gen-map-series",
        "--sites", str(sites), "--events", str(events),
        "--specs", str(_spec_dir(tmp_path)), "--dry-run",
    ])
    assert result.exit_code == 0, result.output
    assert "4 map job" in result.output


def test_export_without_arcpy_is_clean_guard_error(tmp_path):
    result = CliRunner().invoke(autogis, [
        "envmon", "gen-map-series",
        "--sites", "SITE-A", "--events", "2026Q2",
        "--specs", str(_spec_dir(tmp_path)),
        "--gdb", str(tmp_path / "fake.gdb"), "--out-dir", str(tmp_path / "out"),
    ])
    assert result.exit_code != 0
    assert "arcpy" in result.output.lower() or "ArcGIS Pro" in result.output
    assert "Traceback" not in result.output


def test_export_requires_gdb_and_out_dir(tmp_path):
    result = CliRunner().invoke(autogis, [
        "envmon", "gen-map-series",
        "--sites", "SITE-A", "--events", "2026Q2",
        "--specs", str(_spec_dir(tmp_path)),
    ])
    assert result.exit_code != 0
    assert "--gdb" in result.output or "--out-dir" in result.output


def test_duplicate_figure_spec_id_is_refused(tmp_path):
    """Two spec files declaring one figure_spec_id collapsed to whichever
    sorted last — the packet lost a real figure and the job count was reduced
    to match, so nothing looked wrong (#470)."""
    d = _spec_dir(tmp_path)
    # a *different* figure whose id was left unchanged by a copy-paste
    (d / "soil_fig2.yaml").write_text(
        _SPEC_YAML.replace("map_type: GW_ANALYTICAL", "map_type: SOIL"),
        encoding="utf-8")
    result = CliRunner().invoke(autogis, [
        "envmon", "gen-map-series",
        "--sites", "SITE-A", "--events", "2026Q2",
        "--specs", str(d), "--dry-run",
    ])
    assert result.exit_code != 0
    assert "GW_FIG1" in result.output
    # both file names are shown, so the operator can tell which to renumber
    assert "gw_fig1.yaml" in result.output and "soil_fig2.yaml" in result.output
    assert "Traceback" not in result.output


def test_gen_map_series_exposes_overwrite_flag():
    """The combined appendix and the figures now share one overwrite policy
    (#471); the flag is the operator's way to opt out of versioning."""
    result = CliRunner().invoke(autogis, ["envmon", "gen-map-series", "--help"])
    assert "--overwrite" in result.output


def test_empty_spec_dir_is_usage_error(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    result = CliRunner().invoke(autogis, [
        "envmon", "gen-map-series",
        "--sites", "SITE-A", "--events", "2026Q2",
        "--specs", str(d), "--dry-run",
    ])
    assert result.exit_code != 0
    assert "figure-spec" in result.output.lower()
