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
