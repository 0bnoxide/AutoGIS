"""Tool 7.5 FieldMapsSyncPreflight — pure-check tests (headless, no arcgis)."""
from datetime import date

from autogis.core.agol.audit_schema import diff_schema
from autogis.core.agol.fieldmaps_preflight import (
    build_preflight_report,
    check_attachments,
    check_conflict_candidates,
    check_duplicate_identities,
    check_pending_hosted_edits,
    check_replica_age,
    check_sync_config,
    drift_findings,
    edit_date_field,
    format_preflight_report,
)
from autogis.core.agol.sync_layer import edits_where_clause
from autogis.core.common.qa import SEV_INFO, SEV_WARNING

_MS_PER_DAY = 86_400_000

GOOD_SERVICE = {
    "syncEnabled": True,
    "capabilities": "Query,Sync,Extract",
    "editorTrackingInfo": {"enableEditorTracking": True},
}
GOOD_LAYER = {
    "name": "MonitoringWells",
    "globalIdField": "GlobalID",
    "hasAttachments": True,
    "editFieldsInfo": {"editDateField": "EditDate"},
}


def _warnings(findings):
    return [f for f in findings if f.severity == SEV_WARNING]


# -- edits_where_clause edit_field (shared sync_layer fix) ---------------------

def test_where_clause_default_field_unchanged():
    assert edits_where_clause(None, date(2026, 1, 1)).startswith("EditDate > ")


def test_where_clause_custom_edit_field():
    clause = edits_where_clause(None, date(2026, 1, 1),
                                edit_field="last_edited_date")
    assert clause.startswith("last_edited_date > ")


# -- edit_date_field -----------------------------------------------------------

def test_edit_date_field_from_props():
    assert edit_date_field(
        {"editFieldsInfo": {"editDateField": "last_edited_date"}}
    ) == "last_edited_date"


def test_edit_date_field_fallback():
    assert edit_date_field({}) == "EditDate"
    assert edit_date_field({"editFieldsInfo": {}}) == "EditDate"


# -- check_sync_config ---------------------------------------------------------

def test_sync_config_clean():
    findings = check_sync_config(GOOD_SERVICE, GOOD_LAYER)
    assert not _warnings(findings)
    assert findings[-1].message == "sync configuration OK"


def test_sync_config_sync_disabled():
    props = dict(GOOD_SERVICE, syncEnabled=False)
    subjects = {f.subject for f in _warnings(check_sync_config(props,
                                                              GOOD_LAYER))}
    assert "syncEnabled" in subjects


def test_sync_config_capability_string_inconsistent():
    props = dict(GOOD_SERVICE, capabilities="Query,Editing")
    subjects = {f.subject for f in _warnings(check_sync_config(props,
                                                              GOOD_LAYER))}
    assert "capabilities" in subjects


def test_sync_config_editor_tracking_off():
    props = dict(GOOD_SERVICE,
                 editorTrackingInfo={"enableEditorTracking": False})
    subjects = {f.subject for f in _warnings(check_sync_config(props,
                                                              GOOD_LAYER))}
    assert "editorTrackingInfo" in subjects


def test_sync_config_no_globalid():
    layer = dict(GOOD_LAYER, globalIdField="")
    subjects = {f.subject for f in _warnings(check_sync_config(GOOD_SERVICE,
                                                               layer))}
    assert "globalIdField" in subjects


def test_sync_config_attachments_disabled_is_info_only():
    layer = dict(GOOD_LAYER, hasAttachments=False)
    findings = check_sync_config(GOOD_SERVICE, layer)
    assert not _warnings(findings)
    assert any(f.subject == "hasAttachments" and f.severity == SEV_INFO
               for f in findings)


# -- check_pending_hosted_edits ------------------------------------------------

def test_pending_edits_with_since():
    (f,) = check_pending_hosted_edits([{"a": 1}, {"a": 2}],
                                      since="2026-07-01")
    assert f.severity == SEV_INFO
    assert "2 hosted record(s) edited since 2026-07-01" in f.message


def test_pending_edits_without_since_notes_full_layer():
    (f,) = check_pending_hosted_edits([{"a": 1}])
    assert "no --since watermark" in f.message


# -- check_replica_age ---------------------------------------------------------

def test_replica_age_empty():
    (f,) = check_replica_age([], now_ms=0, max_age_days=7)
    assert f.severity == SEV_INFO
    assert "no replicas" in f.message


def test_replica_age_fresh_and_stale():
    now = 100 * _MS_PER_DAY
    replicas = [
        {"replicaName": "fresh", "lastSyncDate": now - 2 * _MS_PER_DAY},
        {"replicaName": "stale", "lastSyncDate": now - 30 * _MS_PER_DAY},
    ]
    findings = check_replica_age(replicas, now_ms=now, max_age_days=7)
    by_subject = {f.subject: f for f in findings}
    assert by_subject["fresh"].severity == SEV_INFO
    assert by_subject["stale"].severity == SEV_WARNING
    assert "30.0 day(s)" in by_subject["stale"].message


def test_replica_age_falls_back_to_creation_date():
    now = 100 * _MS_PER_DAY
    (f,) = check_replica_age(
        [{"replicaName": "r", "creationDate": now - 1 * _MS_PER_DAY}],
        now_ms=now, max_age_days=7)
    assert "(creation)" in f.message


def test_replica_age_missing_dates_warns():
    (f,) = check_replica_age([{"replicaName": "r"}], now_ms=0, max_age_days=7)
    assert f.severity == SEV_WARNING
    assert "age unknown" in f.message


# -- drift_findings ------------------------------------------------------------

_SPEC = {"layer_name": "L",
         "fields": [{"name": "LocationID", "type": "esriFieldTypeString"}]}


def test_drift_findings_clean():
    report = diff_schema(
        {"fields": [{"name": "LocationID",
                     "type": "esriFieldTypeString"}]}, _SPEC)
    (f,) = drift_findings(report)
    assert f.severity == SEV_INFO


def test_drift_findings_warn_per_item():
    report = diff_schema({"fields": []}, _SPEC)
    findings = drift_findings(report)
    assert findings and all(f.severity == SEV_WARNING for f in findings)
    assert findings[0].subject == "LocationID"
    assert "MISSING_FIELD" in findings[0].message


# -- check_duplicate_identities ------------------------------------------------

def test_duplicates_none():
    (f,) = check_duplicate_identities(
        [{"GlobalID": "a"}, {"GlobalID": "b"}])
    assert f.severity == SEV_INFO


def test_duplicates_detected_with_count():
    findings = check_duplicate_identities(
        [{"GlobalID": "a"}, {"GlobalID": "a"}, {"GlobalID": "b"}])
    (dup,) = _warnings(findings)
    assert dup.subject == "a" and "appears 2 times" in dup.message


def test_duplicates_blank_keys_warn():
    findings = check_duplicate_identities([{"GlobalID": ""}, {"other": 1}])
    (blank,) = _warnings(findings)
    assert "2 hosted record(s) have no GlobalID" in blank.message


def test_duplicates_capped_at_max_listed_with_aggregate():
    # 25 duplicated keys -> 20 itemized + one "...and 5 more" aggregate.
    records = [{"GlobalID": f"k{i:02d}"} for i in range(25)] * 2
    warnings = _warnings(check_duplicate_identities(records))
    itemized = [f for f in warnings if f.subject]
    (aggregate,) = [f for f in warnings if not f.subject]
    assert len(itemized) == 20
    assert "...and 5 more duplicate GlobalID value(s)" in aggregate.message


# -- check_conflict_candidates -------------------------------------------------

def test_conflicts_differing_field_flagged():
    findings = check_conflict_candidates(
        [{"GlobalID": "a", "Depth": 5, "Status": "OK"}],
        [{"GlobalID": "a", "Depth": "7", "Status": "OK"}])
    (conflict,) = _warnings(findings)
    assert conflict.subject == "a"
    assert "Depth" in conflict.message and "Status" not in conflict.message


def test_conflicts_identical_values_clean():
    findings = check_conflict_candidates(
        [{"GlobalID": "a", "Depth": 5}],
        [{"GlobalID": "a", "Depth": "5"}])   # CSV strings == hosted ints
    assert not _warnings(findings)
    assert ("1 matched record(s), 0 conflict candidate(s)"
            in findings[-1].message)


def test_conflicts_excluded_and_system_fields_ignored():
    findings = check_conflict_candidates(
        [{"GlobalID": "a", "EditDate": 1, "Shape__Area": 2.0, "Depth": 5}],
        [{"GlobalID": "a", "EditDate": "9", "Shape__Area": "3", "Depth": "5"}],
        exclude_fields={"EditDate"})
    assert not _warnings(findings)


def test_conflicts_hosted_only_counted():
    findings = check_conflict_candidates(
        [{"GlobalID": "new1"}], [{"GlobalID": "other"}])
    assert "1 hosted-only record(s)" in findings[-1].message


def test_conflicts_duplicate_local_keys_warn():
    findings = check_conflict_candidates(
        [{"GlobalID": "a", "Depth": 5}],
        [{"GlobalID": "a", "Depth": "5"},
         {"GlobalID": "a", "Depth": "999"}])   # divergent second row
    (collision,) = _warnings(findings)
    assert "1 local CSV row(s) share a GlobalID" in collision.message
    # first row wins the compare, so no conflict candidate:
    assert "0 conflict candidate(s)" in findings[-1].message


# -- check_attachments ---------------------------------------------------------

_HOSTED_ATT = {"objectid": 1, "attachment_id": 10,
               "name": "photo.jpg", "size": 2048}


def test_attachments_all_present():
    (f,) = check_attachments(
        [_HOSTED_ATT],
        [{"objectid": "1", "attachment_id": "10", "size": "2048",
          "status": "downloaded", "saved_path": "Wells/photo.jpg"}])
    assert f.severity == SEV_INFO


def test_attachments_missing_locally():
    (f,) = check_attachments([_HOSTED_ATT], [])
    assert f.severity == SEV_WARNING and "not in the local manifest" in f.message


def test_attachments_size_mismatch_is_stale():
    (f,) = check_attachments(
        [_HOSTED_ATT],
        [{"objectid": "1", "attachment_id": "10", "size": "999",
          "status": "downloaded", "saved_path": "Wells/photo.jpg"}])
    assert f.severity == SEV_WARNING and "stale local copy" in f.message


def test_attachments_failed_harvest_counts_as_missing():
    # Harvester writes failed rows with the hosted size preserved — a size
    # match on a failed row must NOT read as "present locally".
    (f,) = check_attachments(
        [_HOSTED_ATT],
        [{"objectid": "1", "attachment_id": "10", "size": "2048",
          "status": "failed", "disposition": "failed", "saved_path": ""}])
    assert f.severity == SEV_WARNING
    assert "harvest failed" in f.message


def test_attachments_skipped_rows_count_as_present():
    # skipped = file already on disk from a previous run.
    (f,) = check_attachments(
        [_HOSTED_ATT],
        [{"objectid": "1", "attachment_id": "10", "size": "2048",
          "status": "skipped", "disposition": "skipped",
          "saved_path": "Wells/photo.jpg"}])
    assert f.severity == SEV_INFO


def test_attachments_pathless_skipped_row_counts_as_missing():
    (f,) = check_attachments(
        [_HOSTED_ATT],
        [{"objectid": "1", "attachment_id": "10", "size": "2048",
          "status": "skipped", "disposition": "skipped",
          "saved_path": ""}])
    assert f.severity == SEV_WARNING
    assert "no saved path" in f.message


def test_attachments_scoped_to_selected_source_table():
    (f,) = check_attachments(
        [_HOSTED_ATT],
        [
            {"objectid": "1", "attachment_id": "10", "size": "2048",
             "status": "downloaded", "saved_path": "Other/photo.jpg",
             "source_table": "OtherLayer"},
            {"objectid": "1", "attachment_id": "10", "size": "999",
             "status": "downloaded", "saved_path": "Wells/photo.jpg",
             "source_table": "MonitoringWells"},
        ],
        source_table="MonitoringWells",
    )
    assert f.severity == SEV_WARNING
    assert "stale local copy" in f.message


def test_attachments_missing_capped_with_aggregate():
    hosted = [{"objectid": i, "attachment_id": 1, "name": "p.jpg",
               "size": 10} for i in range(25)]
    findings = check_attachments(hosted, [])
    warnings = _warnings(findings)
    itemized = [f for f in warnings if f.subject]
    (aggregate,) = [f for f in warnings if not f.subject]
    assert len(itemized) == 20
    assert "...and 5 more missing attachment(s)" in aggregate.message


# -- report assembly / formatting ----------------------------------------------

def _report(findings, checks_run):
    return build_preflight_report(item_id="abc123", layer_name="Wells",
                                  checks_run=checks_run, findings=findings)


def test_report_warning_flag_and_counts():
    clean = _report(check_sync_config(GOOD_SERVICE, GOOD_LAYER),
                    ["sync_config"])
    assert not clean.has_warnings
    dirty = _report(check_sync_config({}, {}), ["sync_config"])
    assert dirty.has_warnings


def test_format_shows_skipped_sections_and_is_ascii():
    text = format_preflight_report(
        _report(check_sync_config(GOOD_SERVICE, GOOD_LAYER),
                ["sync_config"]))
    assert "Field Maps Sync Preflight  [CLEAN]" in text
    assert "Item: abc123" in text and "Layer: Wells" in text
    assert text.count("SKIPPED (input not provided)") == 6
    text.encode("ascii")  # cp1252-console safety: output must stay ASCII


def test_format_warning_header_and_grouping():
    findings = (check_sync_config(dict(GOOD_SERVICE, syncEnabled=False),
                                  GOOD_LAYER)
                + check_pending_hosted_edits([], since="2026-07-01"))
    text = format_preflight_report(
        _report(findings, ["sync_config", "hosted_edits"]))
    assert "[1 WARNING(S)]" in text
    assert "Sync configuration" in text and "Pending hosted edits" in text
    assert "[WARNING] sync is not enabled" in text
