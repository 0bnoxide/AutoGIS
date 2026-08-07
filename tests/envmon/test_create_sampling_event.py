"""Tests for create_sampling_event — fully arcpy-free."""
import pytest

from autogis.core.envmon.create_sampling_event import (
    build_sampling_event_plan,
    SamplingEventPlan,
    ExpectedSampleRow,
    CrewAssignmentRow,
)

# ── fixtures ──────────────────────────────────────────────────────────────

SITE = {"site_id": "H281", "site_name": "H281 Glasgow"}

EVENT_BASE = {
    "event_name": "2026-Q2",
    "event_date": "2026-07-15",
    "coc_prefix": "H281-COC",
    "lab_name": "TestAmerica Seattle",
    "matrices": ["GW"],
    "location_ids": ["MW-1", "MW-2", "MW-3"],
    "crew_list": ["Alice Smith", "Bob Jones"],
    "dup_frequency": 0,  # off for most tests — enable selectively
    "analyte_groups": {
        "VOCs": ["Benzene", "Toluene"],
        "Metals": ["Arsenic"],
    },
    "group_sampling": {
        "VOCs": {"container": "40mL VOA", "preservative": "HCl",
                 "hold_time_hr": 14, "bottles": 1},
        "Metals": {"container": "250mL PP", "preservative": "HNO3",
                   "hold_time_hr": 180, "bottles": 1},
    },
}

ADICT = {
    "Benzene": {"abbreviation": "B", "analytical_group": "VPH_VOC",
                "default_units_by_matrix": {"GW": "ug/L"}, "display_order": 10},
    "Toluene": {"abbreviation": "T", "analytical_group": "VPH_VOC",
                "default_units_by_matrix": {"GW": "ug/L"}, "display_order": 20},
    "Arsenic": {"abbreviation": "As", "analytical_group": "METALS",
                "default_units_by_matrix": {"GW": "ug/L"}, "display_order": 30},
}

FIXED_RUN_ID = "test-run-001"


def _plan(event_overrides=None) -> SamplingEventPlan:
    event = {**EVENT_BASE, **(event_overrides or {})}
    return build_sampling_event_plan(SITE, event, ADICT, run_id=FIXED_RUN_ID)


# ── row count ─────────────────────────────────────────────────────────────

def test_expected_row_count_no_dups():
    """3 wells × 2 analyte groups × 1 matrix = 6 rows with dup_frequency=0."""
    plan = _plan()
    primary = [r for r in plan.expected_samples if r.sample_type == "Regular"]
    assert len(primary) == 6


def test_field_dup_added_at_frequency():
    """dup_frequency=2 → every 2nd well gets a FD row per analyte_group."""
    # 3 wells ["MW-1","MW-2","MW-3"], freq=2:
    # position 1 (MW-1): 1 % 2 != 0 → no dup
    # position 2 (MW-2): 2 % 2 == 0 → dup
    # position 3 (MW-3): 3 % 2 != 0 → no dup
    # → 1 dup well (MW-2) × 2 groups = 2 FD rows
    plan = _plan({"dup_frequency": 2})
    fd_rows = [r for r in plan.expected_samples if r.sample_type == "Field Duplicate"]
    assert len(fd_rows) == 2
    assert all(r.location_id == "MW-2" for r in fd_rows)


def test_no_field_dups_when_frequency_zero():
    plan = _plan({"dup_frequency": 0})
    assert not any(r.sample_type == "Field Duplicate" for r in plan.expected_samples)


# ── sample ID format ──────────────────────────────────────────────────────

def test_sample_id_format_primary():
    """Primary SampleID = {WellID}-{YYYYMMDD}-{Matrix}."""
    plan = _plan()
    row = next(r for r in plan.expected_samples
               if r.location_id == "MW-1" and r.sample_type == "Regular")
    assert row.sample_id == "MW-1-20260715-GW"


def test_sample_id_format_field_dup():
    """Planned field dup A has the form's explicit A discriminator."""
    plan = _plan({"dup_frequency": 1})  # every well gets a dup
    row = next(r for r in plan.expected_samples
               if r.location_id == "MW-1" and r.sample_type == "Field Duplicate")
    assert row.sample_id == "MW-1-20260715-GW-FD-A"


# ── COC numbering ─────────────────────────────────────────────────────────

def test_coc_numbers_are_sequential():
    """Each well gets its own COC number; numbers are unique and sequential."""
    plan = _plan()
    coc_by_well = {}
    for row in plan.expected_samples:
        coc_by_well.setdefault(row.location_id, row.coc_number)
    coc_nums = list(coc_by_well.values())
    assert len(set(coc_nums)) == 3                        # one per well
    assert coc_nums[0] == "H281-COC-001"
    assert coc_nums[1] == "H281-COC-002"
    assert coc_nums[2] == "H281-COC-003"


# ── crew assignment ───────────────────────────────────────────────────────

def test_crew_round_robin_covers_all_wells():
    """Every well appears in crew_assignments exactly once."""
    plan = _plan()
    assigned = {r.location_id for r in plan.crew_assignments}
    assert assigned == {"MW-1", "MW-2", "MW-3"}


def test_crew_assignment_is_round_robin():
    """With 3 wells and 2 crew, distribution is [2, 1] or [1, 2]."""
    plan = _plan()
    from collections import Counter
    counts = Counter(r.assigned_to for r in plan.crew_assignments)
    totals = sorted(counts.values(), reverse=True)
    assert totals in ([2, 1], [1, 2])


def test_crew_assignment_has_correct_sample_count():
    """bottle count per well = number of analyte_groups × bottles_per_group."""
    plan = _plan()
    row = next(r for r in plan.crew_assignments if r.location_id == "MW-1")
    # 2 groups × 1 bottle each = 2
    assert row.bottle_count == 2


# ── group_sampling metadata propagates ───────────────────────────────────

def test_group_sampling_container_propagated():
    plan = _plan()
    row = next(r for r in plan.expected_samples
               if r.analyte_group == "VOCs" and r.sample_type == "Regular")
    assert row.container_type == "40mL VOA"
    assert row.preservative == "HCl"
    assert row.hold_time_hr == 14


def test_missing_group_sampling_falls_back_to_defaults():
    """If group_sampling omits a group, defaults are empty-string / 0."""
    event = {**EVENT_BASE, "group_sampling": {}}
    plan = build_sampling_event_plan(SITE, event, ADICT, run_id=FIXED_RUN_ID)
    row = next(r for r in plan.expected_samples if r.analyte_group == "VOCs")
    assert row.container_type == ""
    assert row.preservative == ""
    assert row.hold_time_hr == 0


# ── plan metadata ─────────────────────────────────────────────────────────

def test_plan_run_id_is_injected():
    plan = _plan()
    assert plan.run_id == FIXED_RUN_ID


def test_plan_site_id_sourced_from_site_config():
    plan = _plan()
    assert plan.site_id == "H281"


# ── validation guards ─────────────────────────────────────────────────────

def test_empty_crew_list_raises():
    with pytest.raises(ValueError, match="crew_list"):
        _plan({"crew_list": []})


def test_empty_location_ids_raises():
    with pytest.raises(ValueError, match="location_ids"):
        _plan({"location_ids": []})


def test_missing_event_name_raises():
    event = {k: v for k, v in EVENT_BASE.items() if k != "event_name"}
    with pytest.raises(KeyError):
        build_sampling_event_plan(SITE, event, ADICT, run_id=FIXED_RUN_ID)


def test_unknown_analyte_in_analyte_groups_raises():
    """Misspelled analyte that's not in the analyte_dict raises ValueError."""
    event = {**EVENT_BASE, "analyte_groups": {"VOCs": ["Benzene", "Benzine"]}}
    with pytest.raises(ValueError, match="Benzine"):
        build_sampling_event_plan(SITE, event, ADICT, run_id=FIXED_RUN_ID)


def test_dup_well_bottle_count_includes_fd_bottles():
    """CrewAssignmentRow.bottle_count must count both primary and FD bottles."""
    # dup_frequency=1 → every well gets a FD
    plan = _plan({"dup_frequency": 1})
    row = next(r for r in plan.crew_assignments if r.location_id == "MW-1")
    # 2 groups × 1 bottle each × 2 (primary + FD) = 4
    assert row.bottle_count == 4


# ── issue #421: matrices beyond the first were silently dropped ────────────

def test_multiple_matrices_rejected_not_silently_dropped():
    """`matrices: [GW, SO]` used to plan GW only, with no signal -- the crew
    reached the field with no soil bottles and the gap resurfaced later as
    lab-side matrix_mismatch errors."""
    event = dict(EVENT_BASE, matrices=["GW", "SO"])
    with pytest.raises(ValueError) as exc:
        build_sampling_event_plan(SITE, event, ADICT, run_id=FIXED_RUN_ID)
    msg = str(exc.value)
    assert "GW" in msg and "SO" in msg
    assert "one event config per matrix" in msg


def test_single_matrix_still_plans():
    plan = build_sampling_event_plan(
        dict(SITE), dict(EVENT_BASE, matrices=["SO"]), ADICT,
        run_id=FIXED_RUN_ID)
    assert {r.matrix for r in plan.expected_samples} == {"SO"}


# ── issue #437: scalar analyte_groups value bypassed validation ────────────

def test_scalar_analyte_group_value_rejected():
    """`VOCs: Benzene` (a scalar, not a list) skipped the analyte-dictionary
    check entirely and shipped an unvalidated group."""
    event = dict(EVENT_BASE, analyte_groups={"VOCs": "Benzene"})
    with pytest.raises(ValueError) as exc:
        build_sampling_event_plan(SITE, event, ADICT, run_id=FIXED_RUN_ID)
    assert "VOCs" in str(exc.value) and "list" in str(exc.value)


def test_scalar_analyte_group_with_unknown_analyte_still_rejected():
    """The shape check must fire before -- not instead of -- the unknown
    analyte check, so a mis-shaped group never reaches the plan either way."""
    event = dict(EVENT_BASE, analyte_groups={"VOCs": "Nonexistium"})
    with pytest.raises(ValueError):
        build_sampling_event_plan(SITE, event, ADICT, run_id=FIXED_RUN_ID)


def test_empty_analyte_group_list_is_still_accepted():
    """An empty list is a well-formed (if empty) group -- only non-list values
    are rejected."""
    event = dict(EVENT_BASE, analyte_groups={"VOCs": []},
                 group_sampling={})
    plan = build_sampling_event_plan(SITE, event, ADICT, run_id=FIXED_RUN_ID)
    assert [r.analyte_group for r in plan.expected_samples] == ["VOCs"] * 3
