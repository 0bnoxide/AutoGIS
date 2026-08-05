"""tests/envmon/test_reconcile_event.py"""
from autogis.core.envmon import reconcile_event as re_mod
from autogis.core.envmon.sample_id import QC_SUFFIXES, PRIMARY


def test_normalize_key_uppercases_and_strips():
    assert re_mod.normalize_key("  mw-1-20260715-gw ") == "MW-1-20260715-GW"


def test_default_mask_primary_requires_downstream_plan_optional():
    m = re_mod.default_mask("MW-1-20260715-GW")
    assert m["plan"] == re_mod.OPTIONAL          # D3: plan never required
    for s in ("field", "coc", "lab", "gdb"):
        assert m[s] == re_mod.REQUIRED


def test_default_mask_lab_qc_is_lab_only():
    m = re_mod.default_mask("MW-1-20260715-GW-MB")
    assert m["lab"] == re_mod.REQUIRED
    assert m["field"] == re_mod.FORBIDDEN
    assert m["coc"] == re_mod.FORBIDDEN


def test_default_mask_trip_blank_forbids_field():
    m = re_mod.default_mask("MW-1-20260715-GW-TB")
    assert m["field"] == re_mod.FORBIDDEN
    assert m["coc"] == re_mod.REQUIRED
    assert m["lab"] == re_mod.REQUIRED


def test_every_qc_class_has_a_mask():
    # The table must stay exhaustive as sample_id.QC_SUFFIXES evolves.
    classes = set(QC_SUFFIXES.values()) | {PRIMARY}
    for cls in classes:
        assert cls in re_mod.QC_MASKS, cls
    # Each suffix must produce a well-formed ID and match its QC_MASKS entry
    for suffix, cls in QC_SUFFIXES.items():
        # suffix is already dash-prefixed (e.g., "-mb"), uppercase it for the ID
        sample_id = f"MW-1-20260715-GW{suffix.upper()}"
        assert re_mod.default_mask(sample_id) == re_mod.QC_MASKS[cls]


def test_unknown_or_unparseable_id_gets_all_optional_mask():
    m = re_mod.default_mask("GARBAGE!!")
    assert set(m.values()) == {re_mod.OPTIONAL}


def test_duplicate_marker_without_lifecycle_structure_is_all_optional():
    # Non-lifecycle ID with a duplicate marker (e.g., "MW-1-DUP") should get
    # all-optional, not wrongly demand full downstream presence.
    m = re_mod.default_mask("MW-1-DUP")
    assert set(m.values()) == {re_mod.OPTIONAL}


def _legs(**kw):
    return {k: [re_mod.SourceRow(s, a) for s, a in v] for k, v in kw.items()}


def test_build_grid_one_row_per_normalized_id():
    legs = _legs(field=[("mw-1-20260715-gw", {})], lab=[("MW-1-20260715-GW", {})])
    grid = re_mod.build_grid(legs)
    assert list(grid) == ["MW-1-20260715-GW"]
    row = grid["MW-1-20260715-GW"]
    assert row.present["field"] and row.present["lab"]
    assert not row.present["plan"]


def test_build_grid_omitted_leg_mask_forced_optional():
    grid = re_mod.build_grid(_legs(field=[("MW-1-20260715-GW", {})]))
    row = grid["MW-1-20260715-GW"]
    assert row.mask["lab"] == re_mod.OPTIONAL      # lab leg not provided
    assert row.mask["coc"] == re_mod.OPTIONAL


def test_build_grid_override_beats_default():
    ov = {"MW-1-20260715-GW": {"gdb": re_mod.FORBIDDEN}}
    grid = re_mod.build_grid(_legs(field=[("MW-1-20260715-GW", {})],
                                   gdb=[("MW-1-20260715-GW", {})]), overrides=ov)
    assert grid["MW-1-20260715-GW"].mask["gdb"] == re_mod.FORBIDDEN


def test_build_grid_multi_coc_flagged():
    legs = _legs(coc=[("MW-1-20260715-GW", {"coc_number": "COC-001"}),
                      ("MW-1-20260715-GW", {"coc_number": "COC-002"})])
    row = re_mod.build_grid(legs)["MW-1-20260715-GW"]
    assert "multi_coc" in row.codes


def test_build_grid_duplicate_same_coc_not_flagged():
    # 422 shape: planner repeats the same id on the same COC — dedupe silently.
    legs = _legs(coc=[("MW-1-20260715-GW", {"coc_number": "COC-001"}),
                      ("MW-1-20260715-GW", {"coc_number": "COC-001"})])
    assert re_mod.build_grid(legs)["MW-1-20260715-GW"].codes == []


def test_build_grid_conflicting_duplicate_flagged_identical_ignored():
    # Identical repeat (sync retry) stays silent:
    legs = _legs(field=[("MW-1-20260715-GW", {"SampleDate": "2026-07-15"}),
                        ("MW-1-20260715-GW", {"SampleDate": "2026-07-15"})])
    assert re_mod.build_grid(legs)["MW-1-20260715-GW"].codes == []
    # Conflicting repeat is reported, first observation's attrs still win:
    legs = _legs(field=[("MW-1-20260715-GW", {"SampleDate": "2026-07-15"}),
                        ("MW-1-20260715-GW", {"SampleDate": "2026-07-16"})])
    row = re_mod.build_grid(legs)["MW-1-20260715-GW"]
    assert row.codes == ["duplicate_in_field"]
    assert row.attrs["field"]["SampleDate"] == "2026-07-15"


def _judged(legs, **kw):
    grid = re_mod.build_grid(legs)
    for row in grid.values():
        re_mod.judge_row(row, **kw)
    return grid


def test_planned_clean_sample_reconciled():
    a = {"location_id": "MW-1", "event_date": "2026-07-15", "matrix": "GW"}
    legs = _legs(plan=[("MW-1-20260715-GW", a)], field=[("MW-1-20260715-GW", a)],
                 coc=[("MW-1-20260715-GW", {"coc_number": "COC-001"})],
                 lab=[("MW-1-20260715-GW", a)], gdb=[("MW-1-20260715-GW", a)])
    row = _judged(legs)["MW-1-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_RECONCILED
    assert row.origin == "planned"


def test_field_added_sample_reconciled_not_flagged():
    a = {"LocationID": "MW-9", "SampleDate": "2026-07-15", "Matrix": "GW"}
    legs = _legs(field=[("MW-9-20260715-GW", a)],
                 coc=[("MW-9-20260715-GW", {"coc_number": "COC-001"})],
                 lab=[("MW-9-20260715-GW", a)], gdb=[("MW-9-20260715-GW", a)])
    row = _judged(legs)["MW-9-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_RECONCILED
    assert row.origin == "field-added"      # D3: unplanned is legitimate


def test_stalled_after_coc_names_last_stage():
    legs = _legs(field=[("MW-2-20260715-GW", {})],
                 coc=[("MW-2-20260715-GW", {"coc_number": "COC-001"})])
    # lab and gdb legs ARE provided (empty) so their absence is judged
    legs["lab"], legs["gdb"] = [], []
    row = _judged(legs)["MW-2-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_STALLED
    assert row.last_stage == "coc"


def test_not_collected_with_dry_reason():
    legs = _legs(plan=[("MW-3-20260715-GW", {"location_id": "MW-3"})])
    legs["field"] = legs["coc"] = legs["lab"] = legs["gdb"] = []
    row = _judged(legs, dry_wells={"MW-3": "well dry"})["MW-3-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_NOT_COLLECTED
    assert any(c.startswith("dry:") for c in row.codes)


def test_not_collected_without_dry_reason_still_counts_residual():
    # Sanity companion to the dry-well relaxation test below: an undocumented
    # not_collected sample must keep its full residual (F4 only relaxes
    # masks for a *documented* dry well, never a bare gap).
    legs = _legs(plan=[("MW-3-20260715-GW", {"location_id": "MW-3"})])
    legs["field"] = legs["coc"] = legs["lab"] = legs["gdb"] = []
    result = re_mod.reconcile_event(legs)
    assert result.residual == 4
    assert not result.clean


def test_documented_dry_well_contributes_zero_residual_and_clean():
    # F4 / spec §4.1: a dry-annotated not_collected row is informational, not
    # an error -- its downstream REQUIRED masks relax to OPTIONAL so an
    # otherwise-clean event with a documented dry well is still `clean`.
    legs = _legs(plan=[("MW-3-20260715-GW", {"location_id": "MW-3"})])
    legs["field"] = legs["coc"] = legs["lab"] = legs["gdb"] = []
    result = re_mod.reconcile_event(legs, dry_wells={"MW-3": "well dry"})
    row = result.rows[0]
    assert row.outcome == re_mod.OUTCOME_NOT_COLLECTED
    assert any(c.startswith("dry:") for c in row.codes)
    assert result.residual == 0
    assert result.clean


def test_orphan_lab_only_primary():
    legs = _legs(lab=[("MW-4-20260715-GW", {})])
    legs["field"] = legs["coc"] = legs["gdb"] = []
    row = _judged(legs)["MW-4-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_ORPHAN


def test_lab_only_method_blank_is_reconciled():
    legs = _legs(lab=[("MW-4-20260715-GW-MB", {})])
    legs["field"] = legs["coc"] = legs["gdb"] = []
    row = _judged(legs)["MW-4-20260715-GW-MB"]
    assert row.outcome == re_mod.OUTCOME_RECONCILED   # matches its mask


def test_presence_gap_needs_review():
    legs = _legs(field=[("MW-5-20260715-GW", {})], gdb=[("MW-5-20260715-GW", {})])
    legs["coc"], legs["lab"] = [], []
    row = _judged(legs)["MW-5-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_NEEDS_REVIEW
    assert "presence_gap" in row.codes


def test_matrix_mismatch_detail_conflict():
    legs = _legs(field=[("MW-6-20260715-GW", {"Matrix": "GW"})],
                 lab=[("MW-6-20260715-GW", {"matrix": "SO"})],
                 coc=[("MW-6-20260715-GW", {"coc_number": "C1"})],
                 gdb=[("MW-6-20260715-GW", {"Matrix": "GW"})])
    row = _judged(legs)["MW-6-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_DETAIL_CONFLICT
    assert any(c.startswith("matrix_mismatch") for c in row.codes)


def test_stalled_beats_detail_conflict_in_headline():
    legs = _legs(field=[("MW-7-20260715-GW", {"Matrix": "GW"})],
                 coc=[("MW-7-20260715-GW", {"coc_number": "C1", "matrix": "SO"})])
    legs["lab"], legs["gdb"] = [], []
    row = _judged(legs)["MW-7-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_STALLED
    assert any(c.startswith("matrix_mismatch") for c in row.codes)


def test_date_mismatch_detected():
    # Different dates between field and lab → detail_conflict with date_mismatch code.
    legs = _legs(field=[("MW-8-20260715-GW", {"SampleDate": "2026-07-15"})],
                 lab=[("MW-8-20260715-GW", {"sample_date": "2026-07-16"})],
                 coc=[("MW-8-20260715-GW", {"coc_number": "C1"})],
                 gdb=[("MW-8-20260715-GW", {})])
    row = _judged(legs)["MW-8-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_DETAIL_CONFLICT
    assert any(c.startswith("date_mismatch") for c in row.codes)


def test_date_mismatch_tolerant_format():
    # Tolerant format: "2026-07-15" vs "20260715" should NOT flag date_mismatch.
    legs = _legs(field=[("MW-13-20260715-GW", {"SampleDate": "2026-07-15"})],
                 gdb=[("MW-13-20260715-GW", {"sample_date": "20260715"})],
                 coc=[("MW-13-20260715-GW", {"coc_number": "C1"})],
                 lab=[("MW-13-20260715-GW", {})])
    row = _judged(legs)["MW-13-20260715-GW"]
    assert not any(c.startswith("date_mismatch") for c in row.codes)


def test_coc_number_mismatch_detected():
    # Field COCNumber vs coc coc_number mismatch → detail_conflict.
    legs = _legs(field=[("MW-10-20260715-GW", {"COCNumber": "COC-001"})],
                 coc=[("MW-10-20260715-GW", {"coc_number": "COC-999"})],
                 lab=[("MW-10-20260715-GW", {})],
                 gdb=[("MW-10-20260715-GW", {})])
    row = _judged(legs)["MW-10-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_DETAIL_CONFLICT
    assert "coc_number_mismatch" in row.codes


def test_conflicting_duplicate_is_detail_conflict():
    a = {"LocationID": "MW-9", "SampleDate": "2026-07-15", "Matrix": "GW"}
    b = dict(a, SampleDate="2026-07-16")
    legs = _legs(field=[("MW-9-20260715-GW", a), ("MW-9-20260715-GW", b)],
                 coc=[("MW-9-20260715-GW", {"coc_number": "COC-001"})],
                 lab=[("MW-9-20260715-GW", a)], gdb=[("MW-9-20260715-GW", a)])
    row = _judged(legs)["MW-9-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_DETAIL_CONFLICT
    assert "duplicate_in_field" in row.codes


def test_coc_exception_state_needs_review():
    a = {"LocationID": "MW-9", "SampleDate": "2026-07-15", "Matrix": "GW"}
    legs = _legs(field=[("MW-9-20260715-GW", a)],
                 coc=[("MW-9-20260715-GW",
                       {"coc_number": "COC-001", "state": "exception"})],
                 lab=[("MW-9-20260715-GW", a)], gdb=[("MW-9-20260715-GW", a)])
    row = _judged(legs)["MW-9-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_NEEDS_REVIEW
    assert "coc_exception" in row.codes


def test_coc_pre_release_state_with_lab_is_detail_conflict():
    a = {"LocationID": "MW-9", "SampleDate": "2026-07-15", "Matrix": "GW"}
    coc = lambda state: [("MW-9-20260715-GW",
                          {"coc_number": "COC-001", "state": state})]
    legs = _legs(field=[("MW-9-20260715-GW", a)], coc=coc("draft"),
                 lab=[("MW-9-20260715-GW", a)], gdb=[("MW-9-20260715-GW", a)])
    row = _judged(legs)["MW-9-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_DETAIL_CONFLICT
    assert "coc_state_mismatch:draft" in row.codes
    # A released form whose custody record simply lags the lab is not a
    # conflict -- only pre-release states contradict downstream presence.
    legs = _legs(field=[("MW-9-20260715-GW", a)], coc=coc("released"),
                 lab=[("MW-9-20260715-GW", a)], gdb=[("MW-9-20260715-GW", a)])
    assert _judged(legs)["MW-9-20260715-GW"].outcome == re_mod.OUTCOME_RECONCILED


def test_analyte_missing_and_unexpected():
    # Plan analytes {"VOC", "METALS"} vs lab analytes {"VOC", "PFAS"}
    # → codes for analyte_missing:METALS and analyte_unexpected:PFAS.
    legs = _legs(plan=[("MW-11-20260715-GW", {"analytes": {"VOC", "METALS"}})],
                 field=[("MW-11-20260715-GW", {})],
                 coc=[("MW-11-20260715-GW", {"coc_number": "C1"})],
                 lab=[("MW-11-20260715-GW", {"analytes": {"VOC", "PFAS"}})],
                 gdb=[("MW-11-20260715-GW", {})])
    row = _judged(legs)["MW-11-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_DETAIL_CONFLICT
    assert "analyte_missing:METALS" in row.codes
    assert "analyte_unexpected:PFAS" in row.codes


def test_unexpected_in_forbidden_source():
    # Trip blank in field (forbidden) → code "unexpected_in_field" and detail_conflict.
    legs = _legs(field=[("MW-12-20260715-GW-TB", {})],
                 coc=[("MW-12-20260715-GW-TB", {"coc_number": "C1"})],
                 lab=[("MW-12-20260715-GW-TB", {})])
    legs["gdb"] = []
    row = _judged(legs)["MW-12-20260715-GW-TB"]
    assert row.outcome == re_mod.OUTCOME_DETAIL_CONFLICT
    assert "unexpected_in_field" in row.codes


def test_reconcile_event_residual_zero_when_all_masks_met():
    a = {"location_id": "MW-1", "event_date": "2026-07-15", "matrix": "GW"}
    legs = _legs(plan=[("MW-1-20260715-GW", a)], field=[("MW-1-20260715-GW", a)],
                 coc=[("MW-1-20260715-GW", {"coc_number": "C1"})],
                 lab=[("MW-1-20260715-GW", a)], gdb=[("MW-1-20260715-GW", a)])
    result = re_mod.reconcile_event(legs)
    assert result.residual == 0
    assert result.clean


def test_reconcile_event_stalled_sample_breaks_balance():
    legs = _legs(field=[("MW-2-20260715-GW", {})])
    legs["coc"] = legs["lab"] = legs["gdb"] = []
    result = re_mod.reconcile_event(legs)
    assert result.residual == 3          # coc, lab, gdb required-missing
    assert not result.clean


def test_garbled_sample_form_row_is_needs_review_not_observation():
    result = re_mod.reconcile_event({"field": []}, garbled=["???"])
    assert len(result.rows) == 1
    assert result.rows[0].outcome == re_mod.OUTCOME_NEEDS_REVIEW
    assert "unparseable_sample_id" in result.rows[0].codes
    assert not result.clean


def test_suggest_pairs_near_miss_same_class_only():
    legs = _legs(field=[("MW-03-20260801-GW", {})], lab=[("MW03-20260801-GW", {})])
    legs["coc"], legs["gdb"] = [], []
    result = re_mod.reconcile_event(legs)
    pairs = {(s["missing"], s["candidate"]) for s in result.suggestions}
    assert any("MW-03-20260801-GW" in p and "MW03-20260801-GW" in p for p in pairs)


def test_separator_variant_near_miss_promotes_both_to_needs_review():
    legs = _legs(field=[("MW-03-20260801-GW", {})], lab=[("MW03-20260801-GW", {})])
    legs["coc"], legs["gdb"] = [], []
    result = re_mod.reconcile_event(legs)
    by = {r.key: r for r in result.rows}
    assert by["MW-03-20260801-GW"].outcome == re_mod.OUTCOME_NEEDS_REVIEW
    assert by["MW03-20260801-GW"].outcome == re_mod.OUTCOME_NEEDS_REVIEW
    assert "near_miss:MW03-20260801-GW" in by["MW-03-20260801-GW"].codes
    assert "near_miss:MW-03-20260801-GW" in by["MW03-20260801-GW"].codes
    assert not result.clean


def test_plain_near_miss_stays_informational():
    # MW-2 vs MW-4: high edit-similarity but different alphanumerics -- a
    # genuinely different well, not a typo. The stalled side keeps its outcome
    # (billing: work performed); the pair remains an unapplied suggestion.
    legs = _legs(field=[("MW-2-20260801-GW", {})], lab=[("MW-4-20260801-GW", {})])
    legs["coc"], legs["gdb"] = [], []
    result = re_mod.reconcile_event(legs)
    by = {r.key: r for r in result.rows}
    assert by["MW-2-20260801-GW"].outcome == re_mod.OUTCOME_STALLED
    assert by["MW-4-20260801-GW"].outcome == re_mod.OUTCOME_ORPHAN
    assert result.suggestions and not any(
        s["separator_variant"] for s in result.suggestions)


def test_suggest_never_offers_nodate():
    legs = _legs(field=[("MW-03-NODATE-ABC123-GW", {})],
                 lab=[("MW03-NODATE-ABC123-GW", {})])
    legs["coc"], legs["gdb"] = [], []
    result = re_mod.reconcile_event(legs)
    assert result.suggestions == []


def test_csv_and_summary_roundtrip(tmp_path):
    legs = _legs(field=[("MW-1-20260715-GW", {})])
    legs["coc"] = legs["lab"] = legs["gdb"] = []
    result = re_mod.reconcile_event(legs, observations={"water_levels": 3})
    out = tmp_path / "recon.csv"
    re_mod.rows_to_csv(result, out)
    text = out.read_text(encoding="utf-8")
    assert "SampleID" in text and "MW-1-20260715-GW" in text
    summary = re_mod.summary_dict(result)
    assert summary["observations"] == {"water_levels": 3}
    assert summary["residual"] == result.residual
    assert "field" in summary["legs_run"]


def test_golden_event_every_outcome_and_balance_explains_residual():
    a = lambda loc: {"location_id": loc, "event_date": "2026-07-15", "matrix": "GW"}
    C = lambda n: {"coc_number": n}
    legs = {
        "plan": [re_mod.SourceRow("MW-1-20260715-GW", a("MW-1")),    # clean planned
                 re_mod.SourceRow("MW-3-20260715-GW", a("MW-3")),    # dry / not collected
                 re_mod.SourceRow("MW-6-20260715-GW", a("MW-6"))],   # detail conflict
        "field": [re_mod.SourceRow("MW-1-20260715-GW", a("MW-1")),
                  re_mod.SourceRow("MW-9-20260715-GW", a("MW-9")),   # field-added clean
                  re_mod.SourceRow("MW-2-20260715-GW", a("MW-2")),   # stalled after coc
                  re_mod.SourceRow("MW-5-20260715-GW", a("MW-5")),   # presence gap
                  re_mod.SourceRow("MW-6-20260715-GW", a("MW-6"))],
        "coc": [re_mod.SourceRow("MW-1-20260715-GW", C("C1")),
                re_mod.SourceRow("MW-9-20260715-GW", C("C1")),
                re_mod.SourceRow("MW-2-20260715-GW", C("C1")),
                re_mod.SourceRow("MW-6-20260715-GW", C("C1")),
                re_mod.SourceRow("MW-8-20260715-GW", C("C1")),       # multi-coc
                re_mod.SourceRow("MW-8-20260715-GW", C("C2"))],
        "lab": [re_mod.SourceRow("MW-1-20260715-GW", a("MW-1")),
                re_mod.SourceRow("MW-9-20260715-GW", a("MW-9")),
                re_mod.SourceRow("MW-6-20260715-GW",
                                 {"location_id": "MW-6", "matrix": "SO",
                                  "sample_date": "2026-07-15"}),      # matrix conflict
                re_mod.SourceRow("MW-4-20260715-GW", a("MW-4")),      # orphan
                re_mod.SourceRow("MW-1-20260715-GW-MB", {}),          # lab QC, mask-clean
                re_mod.SourceRow("MW-8-20260715-GW", a("MW-8"))],
        "gdb": [re_mod.SourceRow("MW-1-20260715-GW", a("MW-1")),
                re_mod.SourceRow("MW-9-20260715-GW", a("MW-9")),
                re_mod.SourceRow("MW-5-20260715-GW", a("MW-5")),
                re_mod.SourceRow("MW-6-20260715-GW", a("MW-6")),
                re_mod.SourceRow("MW-8-20260715-GW", a("MW-8"))],
    }
    result = re_mod.reconcile_event(
        legs, dry_wells={"MW-3": "well dry"}, garbled=["??bad-row??"],
        observations={"water_levels": 4, "site_conditions": 2})
    by = {r.key: r.outcome for r in result.rows}
    assert by["MW-1-20260715-GW"] == re_mod.OUTCOME_RECONCILED
    assert by["MW-9-20260715-GW"] == re_mod.OUTCOME_RECONCILED
    assert by["MW-1-20260715-GW-MB"] == re_mod.OUTCOME_RECONCILED
    assert by["MW-2-20260715-GW"] == re_mod.OUTCOME_STALLED
    assert by["MW-3-20260715-GW"] == re_mod.OUTCOME_NOT_COLLECTED
    assert by["MW-4-20260715-GW"] == re_mod.OUTCOME_ORPHAN
    assert by["MW-5-20260715-GW"] == re_mod.OUTCOME_NEEDS_REVIEW
    assert by["MW-6-20260715-GW"] == re_mod.OUTCOME_DETAIL_CONFLICT
    assert by["MW-8-20260715-GW"] == re_mod.OUTCOME_NEEDS_REVIEW   # multi-coc
    assert by["UNPARSEABLE:??bad-row??"] == re_mod.OUTCOME_NEEDS_REVIEW
    assert not result.clean
    # Grid membership pinned exactly: the 9 sample keys + 1 UNPARSEABLE row,
    # nothing more (observations must never leak into the grid as rows).
    assert len(result.rows) == 10
    assert set(by) == {
        "MW-1-20260715-GW", "MW-9-20260715-GW", "MW-1-20260715-GW-MB",
        "MW-2-20260715-GW", "MW-3-20260715-GW", "MW-4-20260715-GW",
        "MW-5-20260715-GW", "MW-6-20260715-GW", "MW-8-20260715-GW",
        "UNPARSEABLE:??bad-row??",
    }
    # Residual derived by hand from the fixture's masks (all primary rows are
    # plan=optional, field/coc/lab/gdb=required; MB is lab=required, rest
    # forbidden; UNPARSEABLE is all-optional) -- required-absent count per row:
    #   MW-1: all 5 present                              -> 0
    #   MW-9: field/coc/lab/gdb present (plan optional)   -> 0
    #   MW-1-...-MB: lab present, others forbidden-absent -> 0
    #   MW-2: field,coc present; lab,gdb absent           -> 2
    #   MW-3: dry well (F4/spec §4.1) -- documented, so its downstream
    #         REQUIRED masks relax to OPTIONAL: 0 residual, not 4
    #   MW-4: only lab present; field,coc,gdb absent      -> 3
    #   MW-5: field,gdb present; coc,lab absent           -> 2
    #   MW-6: all 5 present                               -> 0
    #   MW-8: coc,lab,gdb present; field absent           -> 1
    #   UNPARSEABLE: all-optional mask, nothing required  -> 0
    # total = 2+0+3+2+1 = 8
    assert result.residual == 8
    # Every point of residual is explained by a named row (recomputed sum
    # matches the hand-derived total above):
    explained = sum(
        sum(1 for s in re_mod.SOURCES
            if r.mask[s] == re_mod.REQUIRED and not r.present[s])
        + sum(1 for s in re_mod.SOURCES
              if r.mask[s] == re_mod.FORBIDDEN and r.present[s])
        for r in result.rows)
    assert result.residual == explained
    # Observations stayed out of the grid but in the summary:
    s = re_mod.summary_dict(result)
    assert s["observations"] == {"water_levels": 4, "site_conditions": 2}


# ── CLI end-to-end ───────────────────────────────────────────────
import json
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def _field_csv(tmp_path, rows):
    # Columns per Survey123Field defaults (normalize_survey123.py:28-36)
    p = tmp_path / "subs.csv"
    hdr = "WellID,SamplingDate,Matrix,SampledBy,COCNumber,DepthToWater_ft,QAFlags"
    p.write_text(hdr + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return p


def _plan_configs(tmp_path, *, groups):
    """Minimal site/event/analytes fixture -- same shape as
    tests/envmon/test_custody.py's _reference_event helper. ``groups`` is the
    event config's analyte_groups: {group_name: [canonical analyte names]}."""
    site = tmp_path / "site.json"
    site.write_text(json.dumps({
        "site_id": "SITE1", "site_name": "Site One", "project_number": "P-001",
        "address": "1 Test St", "city": "Anytown", "state": "MT",
        "coordinate_system": "NAD83 / UTM Zone 12N", "default_gdb": "SITE1.gdb",
        "default_aprx_template": "template.aprx",
        "monitoring_wells_fc": "MonitoringWells", "soil_borings_fc": "SoilBorings",
        "site_boundary_fc": "SiteBoundary"}), encoding="utf-8")
    event = tmp_path / "event.json"
    event.write_text(json.dumps({
        "event_name": "2026-Q2", "event_date": "2026-07-15",
        "coc_prefix": "COC", "lab_name": "TestLab",
        "matrices": ["GW"], "location_ids": ["MW-1", "MW-2"],
        "crew_list": ["Alice"], "dup_frequency": 0,
        "analyte_groups": groups,
    }), encoding="utf-8")
    analytes = tmp_path / "analytes.json"
    names = {n for members in groups.values() for n in members}
    analytes.write_text(
        json.dumps({"analytes": {n: {} for n in names}}), encoding="utf-8")
    return site, event, analytes


def _lab_csv(tmp_path, rows):
    """rows: iterable of (SampleID, LocationID, AnalyteCanonicalName)."""
    p = tmp_path / "lab.csv"
    hdr = "SampleID,LocationID,SampleDate,Matrix,AnalyteCanonicalName"
    lines = [hdr] + [f"{sid},{loc},2026-07-15,GW,{analyte}"
                     for sid, loc, analyte in rows]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_reconcile_event_in_help():
    res = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "reconcile-event" in res.output


def test_reconcile_event_field_only_clean_exit_zero(tmp_path):
    subs = _field_csv(tmp_path, ["MW-1,2026-07-15,GW,AB,COC-001,,"])
    out_csv, out_json = tmp_path / "r.csv", tmp_path / "r.json"
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event", "--site-id", "SITE1",
        "--submissions-csv", str(subs),
        "--out-csv", str(out_csv), "--out-json", str(out_json)])
    assert res.exit_code == 0, res.output
    summary = json.loads(out_json.read_text(encoding="utf-8"))
    assert summary["clean"] is True
    assert summary["legs_run"] == ["field"]
    assert summary["observations"]                      # water-level block exists


def test_reconcile_event_stalled_exits_2(tmp_path):
    subs = _field_csv(tmp_path, ["MW-1,2026-07-15,GW,AB,COC-001,,"])
    store = tmp_path / "custody.json"
    store.write_text("{}", encoding="utf-8")            # provided but empty COC leg
    out_csv, out_json = tmp_path / "r.csv", tmp_path / "r.json"
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event", "--site-id", "SITE1",
        "--submissions-csv", str(subs), "--custody-store", str(store),
        "--out-csv", str(out_csv), "--out-json", str(out_json)])
    assert res.exit_code == 2, res.output
    # SIDE_EFFECT_SAFETY: outputs must be written before the semantic exit,
    # not skipped by it -- a regression that raised exit 2 before writing
    # would still pass on exit_code alone.
    assert out_csv.exists() and out_json.exists()
    assert "MW-1-20260715-GW" in out_csv.read_text(encoding="utf-8")
    summary = json.loads(out_json.read_text(encoding="utf-8"))
    assert summary["clean"] is False


def test_reconcile_event_no_legs_is_usage_error(tmp_path):
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event", "--site-id", "SITE1",
        "--out-csv", str(tmp_path / "r.csv"), "--out-json", str(tmp_path / "r.json")])
    assert res.exit_code != 0
    assert "at least one" in res.output.lower()


def test_reconcile_event_registered_in_capabilities():
    from autogis.runtime.capabilities import TOOLS, requires_arcpy
    assert "reconcile-event" in TOOLS
    assert requires_arcpy("reconcile-event") is False


def test_reconcile_event_semantic_exit_logs_run_history_success(tmp_path, monkeypatch):
    """A non-clean reconciliation (exit 2) records status=success in run
    history, not error -- a discrepancy finding is not a tool failure (same
    fix class as diff-survey-schema's exit 3, ADR-0115)."""
    import csv as csv_mod

    subs = _field_csv(tmp_path, ["MW-1,2026-07-15,GW,AB,COC-001,,"])
    store = tmp_path / "custody.json"
    store.write_text("{}", encoding="utf-8")
    hist = tmp_path / "run_history.csv"
    monkeypatch.setenv("AUTOGIS_RUN_HISTORY", str(hist))
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event", "--site-id", "SITE1",
        "--submissions-csv", str(subs), "--custody-store", str(store),
        "--out-csv", str(tmp_path / "r.csv"), "--out-json", str(tmp_path / "r.json")])
    assert res.exit_code == 2
    with hist.open(newline="", encoding="utf-8") as fh:
        rows = [row for row in csv_mod.DictReader(fh)
                if row["tool_name"] == "reconcile-event"]
    assert rows and rows[-1]["status"] == "success"


# ── Final-review fix wave: analyte vocabulary, override validation, JSON errors ──

def test_reconcile_event_plan_lab_analyte_vocabulary_matches(tmp_path):
    """Finding 1: the plan leg must expand analyte GROUP names to member
    analytes (same vocabulary as the lab leg's AnalyteCanonicalName), or
    judge_row's set compare mismatches on every plan+lab run."""
    site, event, analytes = _plan_configs(
        tmp_path, groups={"VOCs": ["Benzene", "Toluene"]})
    lab = _lab_csv(tmp_path, [
        ("MW-1-20260715-GW", "MW-1", "Benzene"),
        ("MW-1-20260715-GW", "MW-1", "Toluene"),
        ("MW-2-20260715-GW", "MW-2", "Benzene"),
        ("MW-2-20260715-GW", "MW-2", "Toluene"),
    ])
    out_csv, out_json = tmp_path / "r.csv", tmp_path / "r.json"
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event",
        "--site", str(site), "--event", str(event), "--analytes", str(analytes),
        "--lab-results-csv", str(lab),
        "--out-csv", str(out_csv), "--out-json", str(out_json)])
    assert res.exit_code == 0, res.output
    text = out_csv.read_text(encoding="utf-8")
    assert "analyte_missing" not in text
    assert "analyte_unexpected" not in text
    summary = json.loads(out_json.read_text(encoding="utf-8"))
    assert summary["clean"] is True


def test_reconcile_event_plan_lab_analyte_missing_member(tmp_path):
    """Same fixture, lab leg missing one group member for MW-1 ->
    analyte_missing:<that member> (not a blanket group-name mismatch)."""
    site, event, analytes = _plan_configs(
        tmp_path, groups={"VOCs": ["Benzene", "Toluene"]})
    lab = _lab_csv(tmp_path, [
        ("MW-1-20260715-GW", "MW-1", "Benzene"),      # Toluene missing
        ("MW-2-20260715-GW", "MW-2", "Benzene"),
        ("MW-2-20260715-GW", "MW-2", "Toluene"),
    ])
    out_csv, out_json = tmp_path / "r.csv", tmp_path / "r.json"
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event",
        "--site", str(site), "--event", str(event), "--analytes", str(analytes),
        "--lab-results-csv", str(lab),
        "--out-csv", str(out_csv), "--out-json", str(out_json)])
    # detail_conflict alone doesn't flip result.clean (residual/needs_review
    # only, pre-existing engine semantics) -- exit 0 is expected here; what
    # this test pins is the specific code, not the exit path.
    assert res.exit_code == 0, res.output
    text = out_csv.read_text(encoding="utf-8")
    assert "analyte_missing:Toluene" in text


def test_reconcile_event_plan_analyte_group_scalar_is_rejected_upstream(tmp_path):
    """A YAML/JSON scalar under a group key (not a list) is a malformed event
    config. Since issue #437 the planner rejects it outright, so the plan leg
    fails with a clean ClickException instead of producing a plan built from an
    unvalidated group -- and it is never iterated character-by-character
    (["B","e","n",...]) into attrs["analytes"]."""
    site, event, analytes = _plan_configs(tmp_path, groups={"VOCs": ["Benzene"]})
    # Overwrite with a scalar group value after _plan_configs built the
    # analyte dict from the (list-shaped) groups it was given.
    event.write_text(json.dumps({
        "event_name": "2026-Q2", "event_date": "2026-07-15",
        "coc_prefix": "COC", "lab_name": "TestLab",
        "matrices": ["GW"], "location_ids": ["MW-1", "MW-2"],
        "crew_list": ["Alice"], "dup_frequency": 0,
        "analyte_groups": {"VOCs": "Benzene"},        # scalar, not a list
    }), encoding="utf-8")
    lab = _lab_csv(tmp_path, [("MW-1-20260715-GW", "MW-1", "Benzene")])
    out_csv, out_json = tmp_path / "r.csv", tmp_path / "r.json"
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event",
        "--site", str(site), "--event", str(event), "--analytes", str(analytes),
        "--lab-results-csv", str(lab),
        "--out-csv", str(out_csv), "--out-json", str(out_json)])
    assert res.exit_code != 0
    assert "plan leg failed" in res.output and "VOCs" in res.output
    assert not out_csv.exists() and not out_json.exists()


def test_reconcile_event_plan_empty_analyte_group_is_unresolved_not_chars(tmp_path):
    """The reconciler's own group->member expansion still has to stay loud for
    the shapes the planner accepts: an empty member list resolves to nothing,
    so the group NAME stands in and one QA warning is emitted per group."""
    site, event, analytes = _plan_configs(tmp_path, groups={"VOCs": ["Benzene"]})
    event.write_text(json.dumps({
        "event_name": "2026-Q2", "event_date": "2026-07-15",
        "coc_prefix": "COC", "lab_name": "TestLab",
        "matrices": ["GW"], "location_ids": ["MW-1", "MW-2"],
        "crew_list": ["Alice"], "dup_frequency": 0,
        "analyte_groups": {"VOCs": []},               # accepted, but no members
    }), encoding="utf-8")
    lab = _lab_csv(tmp_path, [("MW-1-20260715-GW", "MW-1", "Benzene")])
    out_csv, out_json = tmp_path / "r.csv", tmp_path / "r.json"
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event",
        "--site", str(site), "--event", str(event), "--analytes", str(analytes),
        "--lab-results-csv", str(lab),
        "--out-csv", str(out_csv), "--out-json", str(out_json)])
    text = out_csv.read_text(encoding="utf-8")
    # Fallback keeps the group NAME ("VOCs") as the plan's stand-in analyte,
    # so MW-1 legitimately mismatches vs the lab's real canonical name
    # ("Benzene") -- a normal analyte_* code, never a per-character one.
    assert "analyte_missing:VOCs" in text
    assert "analyte_missing:B" not in text and "analyte_missing:e" not in text
    # Two wells share the one unresolved group -- exactly one QA record, not
    # one per row.
    assert res.output.count("analyte_group_unresolved") == 1


def test_reconcile_event_presence_override_normalizes_key_and_value(tmp_path):
    """Finding 2: override keys must normalize through engine.normalize_key
    and values must case-fold, or the override is a silent no-op. Forbid the
    (present) field leg via a lowercase key + uppercase value -- without
    normalization this run would stay clean."""
    subs = _field_csv(tmp_path, ["MW-1,2026-07-15,GW,AB,COC-001,,"])
    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        json.dumps({"mw-1-20260715-gw": {"field": "FORBIDDEN"}}),
        encoding="utf-8")
    out_csv, out_json = tmp_path / "r.csv", tmp_path / "r.json"
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event", "--site-id", "SITE1",
        "--submissions-csv", str(subs), "--presence-overrides", str(overrides),
        "--out-csv", str(out_csv), "--out-json", str(out_json)])
    assert res.exit_code == 2, res.output
    assert "unexpected_in_field" in out_csv.read_text(encoding="utf-8")
    summary = json.loads(out_json.read_text(encoding="utf-8"))
    assert summary["clean"] is False


def test_reconcile_event_presence_override_bad_source_is_usage_error(tmp_path):
    subs = _field_csv(tmp_path, ["MW-1,2026-07-15,GW,AB,COC-001,,"])
    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        json.dumps({"MW-1-20260715-GW": {"labb": "required"}}),
        encoding="utf-8")
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event", "--site-id", "SITE1",
        "--submissions-csv", str(subs), "--presence-overrides", str(overrides),
        "--out-csv", str(tmp_path / "r.csv"), "--out-json", str(tmp_path / "r.json")])
    assert res.exit_code != 0
    assert "labb" in res.output


def test_reconcile_event_presence_override_bad_value_is_usage_error(tmp_path):
    subs = _field_csv(tmp_path, ["MW-1,2026-07-15,GW,AB,COC-001,,"])
    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        json.dumps({"MW-1-20260715-GW": {"lab": "FORBIDEN"}}),  # typo
        encoding="utf-8")
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event", "--site-id", "SITE1",
        "--submissions-csv", str(subs), "--presence-overrides", str(overrides),
        "--out-csv", str(tmp_path / "r.csv"), "--out-json", str(tmp_path / "r.json")])
    assert res.exit_code != 0
    assert "FORBIDEN" in res.output


def test_reconcile_event_malformed_presence_overrides_json(tmp_path):
    """Finding 3: malformed JSON -> ClickException with the option name, not
    a raw traceback."""
    subs = _field_csv(tmp_path, ["MW-1,2026-07-15,GW,AB,COC-001,,"])
    bad = tmp_path / "overrides.json"
    bad.write_text("{not json", encoding="utf-8")
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event", "--site-id", "SITE1",
        "--submissions-csv", str(subs), "--presence-overrides", str(bad),
        "--out-csv", str(tmp_path / "r.csv"), "--out-json", str(tmp_path / "r.json")])
    assert res.exit_code != 0
    assert "--presence-overrides" in res.output
    assert "Traceback" not in res.output


def test_reconcile_event_presence_overrides_json_array_rejected(tmp_path):
    """A JSON array top-level currently TypeErrors deep inside build_grid;
    reject it at the CLI boundary instead."""
    subs = _field_csv(tmp_path, ["MW-1,2026-07-15,GW,AB,COC-001,,"])
    bad = tmp_path / "overrides.json"
    bad.write_text("[]", encoding="utf-8")
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event", "--site-id", "SITE1",
        "--submissions-csv", str(subs), "--presence-overrides", str(bad),
        "--out-csv", str(tmp_path / "r.csv"), "--out-json", str(tmp_path / "r.json")])
    assert res.exit_code != 0
    assert "--presence-overrides" in res.output
    assert "Traceback" not in res.output


def test_reconcile_event_malformed_dry_wells_json(tmp_path):
    subs = _field_csv(tmp_path, ["MW-1,2026-07-15,GW,AB,COC-001,,"])
    bad = tmp_path / "dry.json"
    bad.write_text("not json at all", encoding="utf-8")
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event", "--site-id", "SITE1",
        "--submissions-csv", str(subs), "--dry-wells", str(bad),
        "--out-csv", str(tmp_path / "r.csv"), "--out-json", str(tmp_path / "r.json")])
    assert res.exit_code != 0
    assert "--dry-wells" in res.output


# ── PR-review fix wave: F1 key normalization, F2 loud leg failures, F3 ────

def test_reconcile_event_lab_case_variant_ids_union_not_split(tmp_path):
    """F1 (blocker): the lab leg used to group by raw SampleID -- a
    case-variant id across two lab rows for the same sample opened a
    second dict entry, and build_grid's first-observation-wins silently
    dropped that row's analytes instead of union-ing them. Grouping by
    engine.normalize_key fixes it: no analyte_missing/detail_conflict."""
    site, event, analytes = _plan_configs(
        tmp_path, groups={"VOCs": ["Benzene", "Toluene"]})
    lab = _lab_csv(tmp_path, [
        ("mw-1-20260715-gw", "MW-1", "Benzene"),   # lowercase variant
        ("MW-1-20260715-GW", "MW-1", "Toluene"),   # canonical variant
        ("MW-2-20260715-GW", "MW-2", "Benzene"),
        ("MW-2-20260715-GW", "MW-2", "Toluene"),
    ])
    out_csv, out_json = tmp_path / "r.csv", tmp_path / "r.json"
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event",
        "--site", str(site), "--event", str(event), "--analytes", str(analytes),
        "--lab-results-csv", str(lab),
        "--out-csv", str(out_csv), "--out-json", str(out_json)])
    text = out_csv.read_text(encoding="utf-8")
    assert "analyte_missing" not in text
    assert "detail_conflict" not in text
    summary = json.loads(out_json.read_text(encoding="utf-8"))
    assert summary["clean"] is True


def test_reconcile_event_submissions_csv_bad_encoding_is_loud(tmp_path):
    """F2a: a non-UTF8 --submissions-csv must not escape as a raw
    UnicodeDecodeError traceback -- ClickException naming the option and
    file instead."""
    subs = tmp_path / "subs_cp1252.csv"
    hdr = "WellID,SamplingDate,Matrix,SampledBy,COCNumber,DepthToWater_ft,QAFlags"
    row = "MW-1,2026-07-15,GW,André,COC-001,,"   # non-ASCII (cp1252 'é')
    subs.write_bytes((hdr + "\n" + row + "\n").encode("cp1252"))
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event", "--site-id", "SITE1",
        "--submissions-csv", str(subs),
        "--out-csv", str(tmp_path / "r.csv"), "--out-json", str(tmp_path / "r.json")])
    assert res.exit_code != 0
    assert "--submissions-csv" in res.output
    assert "Traceback" not in res.output


def test_reconcile_event_lab_results_wrong_headers_is_loud(tmp_path):
    """F2b: a --lab-results-csv whose headers don't match SampleID/etc.
    used to silently yield all-empty-SampleID records the engine skips,
    reconciling clean with zero signal. Now a hard ClickException."""
    lab = tmp_path / "lab_bad.csv"
    lab.write_text("Foo,Bar\n1,2\n2,3\n", encoding="utf-8")
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event",
        "--lab-results-csv", str(lab),
        "--out-csv", str(tmp_path / "r.csv"), "--out-json", str(tmp_path / "r.json")])
    assert res.exit_code != 0
    assert "SampleID" in res.output


def test_reconcile_event_lab_results_partial_empty_sample_id_warns(tmp_path):
    """F2b: one good row + one empty-SampleID row must still run (the
    empty row is skipped, not fatal), with a QA WARNING naming the count."""
    lab = _lab_csv(tmp_path, [
        ("MW-1-20260715-GW", "MW-1", "Benzene"),
        ("", "MW-2", "Benzene"),
    ])
    out_csv, out_json = tmp_path / "r.csv", tmp_path / "r.json"
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event",
        "--lab-results-csv", str(lab),
        "--out-csv", str(out_csv), "--out-json", str(out_json)])
    assert res.exit_code == 0, res.output
    assert "lab_results_empty_sample_id" in res.output
    assert "1 record" in res.output


def test_reconcile_event_gdb_samples_wrong_headers_is_loud(tmp_path):
    """F2b's same guard on the GDB leg (--gdb-samples-csv), mirroring the
    lab-leg test above -- untested by the reviewer's named list but built
    from the identical wrong-header/empty-SampleID code path."""
    gdb = tmp_path / "gdb_bad.csv"
    gdb.write_text("Foo,Bar\n1,2\n2,3\n", encoding="utf-8")
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event",
        "--gdb-samples-csv", str(gdb),
        "--out-csv", str(tmp_path / "r.csv"), "--out-json", str(tmp_path / "r.json")])
    assert res.exit_code != 0
    assert "SampleID" in res.output


def test_reconcile_event_blank_well_id_is_loud_not_silent(tmp_path):
    """F3: the CLI's garbled/needs_review branch for a blank SampleID is
    dead code at this seam -- normalize_survey123 already rejects a blank
    WellID with a QA ERROR (and drops the row) before that branch could
    ever fire. Pin the loud behavior: QA ERROR in output, non-zero exit,
    no silent drop."""
    subs = _field_csv(tmp_path, [",2026-07-15,GW,AB,COC-001,,"])   # blank WellID
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event", "--site-id", "SITE1",
        "--submissions-csv", str(subs),
        "--out-csv", str(tmp_path / "r.csv"), "--out-json", str(tmp_path / "r.json")])
    assert res.exit_code != 0
    assert "missing_required_field" in res.output
    assert "WellID" in res.output
    assert "Traceback" not in res.output
