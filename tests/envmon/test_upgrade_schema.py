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
    assert len(TABLE_SCHEMAS) == 37, (
        f"Expected 37 tables (9 existing + 28 new), got {len(TABLE_SCHEMAS)}"
    )


def test_env_schema_version_fields():
    fields = {f[0] for f in TABLE_SCHEMAS["Env_SchemaVersion"]}
    assert fields == {
        "SchemaVersion", "UpgradedAt", "PreviousVersion",
        "TablesCreated", "FieldsAdded", "UpgradedBy", "Notes",
    }
