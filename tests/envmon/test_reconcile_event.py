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
        assert cls in re_mod.QC_MASKS or re_mod.UNKNOWN_QC_MASK, cls
        # default_mask must never KeyError on any real suffix:
    for suffix in QC_SUFFIXES:
        re_mod.default_mask(f"MW-1-20260715-GW-{suffix}")


def test_unknown_or_unparseable_id_gets_all_optional_mask():
    m = re_mod.default_mask("GARBAGE!!")
    assert set(m.values()) == {re_mod.OPTIONAL}
