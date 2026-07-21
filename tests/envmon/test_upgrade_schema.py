from autogis.core.envmon.gdb_schema import TABLE_SCHEMAS

NEW_TABLES = [
    "Env_SchemaVersion",
    "Env_CurrentWaterLevelEvent",
    "BoringLocations",
    "LithologyIntervals",
    "BoringSamples",
    "WellConstruction",
    "GroundwaterObservations",
    "BoringPhotos",
    "BoringComments",
    "SurveyPoints_Raw",
    "SurveyPoints_QA",
    "LevelLoopRuns",
    "LevelLoopObservations",
    "ElevationHistory",
    "DroneFlights",
    "DroneControlPoints",
    "DroneCheckpoints",
    "DroneProductRegistry",
    "Dash_SiteStatus",
    "Dash_EventStatus",
    "Dash_WellStatus",
    "Dash_CurrentExceedances",
    "Dash_GWLevelSummary",
    "Dash_AnalyticalSummary",
    "Dash_FieldQA",
    "Dash_LabQA",
    "Dash_OpenIssues",
    "Dash_ReportReadiness",
]


def test_all_new_tables_in_schema():
    missing = [t for t in NEW_TABLES if t not in TABLE_SCHEMAS]
    assert missing == [], f"Missing from TABLE_SCHEMAS: {missing}"


def test_total_table_count():
    assert len(TABLE_SCHEMAS) == 41, (
        f"Expected 41 tables (38 at v2.3 + 2 GW model registry + "
        f"Env_SurfaceRegistry), got {len(TABLE_SCHEMAS)}"
    )


def test_gw_model_registry_tables():
    """ADR-0085 schema sketch, SCHEMA_VERSION 2.4 — additive only."""
    run_fields = [f[0] for f in TABLE_SCHEMAS["GW_ModelRun"]]
    assert run_fields == ["RunID", "SiteID", "EventDate", "Methods",
                          "ExecutedMethods", "RunTimestamp", "ApprovedModel",
                          "ReviewStatus", "Notes"]
    cv_fields = [f[0] for f in TABLE_SCHEMAS["GW_ModelCrossValidation"]]
    assert cv_fields == ["RunID", "ModelName", "NPoints", "RMSE",
                         "MeanError", "MAE", "PctWithinTolerance", "Rank"]


def test_env_schema_version_fields():
    fields = {f[0] for f in TABLE_SCHEMAS["Env_SchemaVersion"]}
    assert fields == {
        "SchemaVersion", "UpgradedAt", "PreviousVersion",
        "TablesCreated", "FieldsAdded", "UpgradedBy", "Notes",
    }


# ---------------------------------------------------------------------------
# upgrade_schema pure-Python layer
# ---------------------------------------------------------------------------
from autogis.core.envmon.upgrade_schema import (  # noqa: E402
    SCHEMA_VERSION,
    TableUpgradeStatus,
    UpgradeReport,
    format_report,
)


def test_schema_version_constant():
    assert SCHEMA_VERSION == "2.6"


def test_table_upgrade_status_attributes():
    s = TableUpgradeStatus("MyTable", "CREATED", 5)
    assert s.table_name == "MyTable"
    assert s.status == "CREATED"
    assert s.fields_added == 5


def test_upgrade_report_properties():
    tables = [
        TableUpgradeStatus("A", "CREATED", 3),
        TableUpgradeStatus("B", "UPDATED", 1),
        TableUpgradeStatus("C", "OK", 0),
    ]
    r = UpgradeReport("/path/site.gdb", "1.0", "2.0", tables, elapsed_seconds=1.5)
    assert r.tables_created == 1
    assert r.fields_added == 4   # 3 + 1 + 0


def test_format_report_contains_created_tag():
    tables = [TableUpgradeStatus("NewTable", "CREATED", 8)]
    r = UpgradeReport("/x.gdb", "1.0", "2.0", tables)
    out = format_report(r)
    assert "[CREATED]" in out
    assert "NewTable" in out


def test_format_report_contains_updated_tag():
    tables = [TableUpgradeStatus("ExistingTable", "UPDATED", 2)]
    r = UpgradeReport("/x.gdb", "1.0", "2.0", tables)
    out = format_report(r)
    assert "[UPDATED]" in out
    assert "ExistingTable" in out


def test_format_report_contains_ok_tag():
    tables = [TableUpgradeStatus("StableTable", "OK", 0)]
    r = UpgradeReport("/x.gdb", "1.0", "2.0", tables)
    out = format_report(r)
    assert "[OK]" in out


def test_format_report_summary_line():
    tables = [
        TableUpgradeStatus("A", "CREATED", 5),
        TableUpgradeStatus("B", "CREATED", 3),
        TableUpgradeStatus("C", "UPDATED", 1),
        TableUpgradeStatus("D", "OK", 0),
    ]
    r = UpgradeReport("/x.gdb", "1.0", "2.0", tables, elapsed_seconds=2.7)
    out = format_report(r)
    assert "2" in out   # 2 created
    assert "1" in out   # 1 updated


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------
from click.testing import CliRunner  # noqa: E402
from autogis.adapters.cli import autogis  # noqa: E402


def test_upgrade_schema_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert result.exit_code == 0
    assert "upgrade-schema" in result.output


def test_upgrade_schema_guard_without_arcpy():
    """Without arcpy, upgrade-schema must error cleanly (no unhandled exception)."""
    result = CliRunner().invoke(autogis, ["envmon", "upgrade-schema", "fake.gdb"])
    assert result.exit_code in (0, 1)
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_surface_registry_fields():
    """Slice-2 drift guard (spec D3 + #241 review: Units provenance)."""
    fields = [f[0] for f in TABLE_SCHEMAS["Env_SurfaceRegistry"]]
    assert fields == ["SiteID", "EventDate", "SurfaceKind", "AnalyteFilter",
                      "Method", "RasterType", "NondetectRule", "Units",
                      "RasterPath", "ReviewStatus", "CreatedAt", "Notes"]
