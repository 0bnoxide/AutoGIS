from autogis.core.envmon.reconcile_locations import normalize_id, reconcile


def test_normalize_id_collapses_separators_and_case():
    assert normalize_id(" mw-07a ") == "MW07A"
    assert normalize_id("MW_07A") == "MW07A"


def test_reconcile_exact_typo_nomatch_and_extra_well():
    workbook = ["MW-1", "MW-7A", "ZZZ-99"]
    wells = ["MW-1", "MW-07A", "MW-2"]
    result = reconcile(workbook, wells, threshold=0.8)

    # MW-1 matches exactly (after normalization both are MW1)
    assert "MW-1" in result.matches
    # MW-7A -> suggestion MW-07A (close), score >= 0.8
    typo = {s.workbook_id: s for s in result.unmatched_workbook}["MW-7A"]
    assert typo.suggestion == "MW-07A" and typo.score >= 0.8
    # ZZZ-99 -> no suggestion above threshold
    nomatch = {s.workbook_id: s for s in result.unmatched_workbook}["ZZZ-99"]
    assert nomatch.suggestion is None
    # MW-2 is a well never sampled in the workbook
    assert "MW-2" in result.unmatched_wells


def test_reconcile_threshold_boundary_excludes_weak_suggestion():
    result = reconcile(["AB"], ["XY"], threshold=0.8)
    assert result.unmatched_workbook[0].suggestion is None


# ---------------------------------------------------------------------------
# Task 2: reconcile_to_qa
# ---------------------------------------------------------------------------
from autogis.core.common.qa import SEV_ERROR, SEV_INFO, SEV_WARNING
from autogis.core.envmon.reconcile_locations import reconcile_to_qa


def test_reconcile_to_qa_severities():
    result = reconcile(["MW-1", "MW-7A", "ZZZ-99"], ["MW-1", "MW-07A", "MW-2"],
                       threshold=0.8)
    qa = reconcile_to_qa(result)
    cats = {(r.severity, r.category) for r in qa.records}
    assert (SEV_WARNING, "location_id_typo") in cats        # MW-7A -> MW-07A
    assert (SEV_ERROR, "location_id_unmatched") in cats      # ZZZ-99
    assert (SEV_INFO, "well_not_sampled") in cats            # MW-2
