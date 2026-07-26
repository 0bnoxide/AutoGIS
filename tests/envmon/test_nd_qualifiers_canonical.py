"""Regression test for issue #340: ND_QUALIFIERS was copy-pasted into seven
report-family modules, none of which included "UJ" -- so a result that
imports as nondetect (result_parser.py's QUALIFIER_FLAGS) reported as a
detect everywhere. All seven now import one canonical set from
core/common/config.py; this pins that it can't silently re-diverge, and that
the canonical set actually agrees with what the importer treats as
nondetect (same pattern as test_known_sheet_data_types_matches_dispatched_set
for #336)."""
from __future__ import annotations

from autogis.core.common.config import ND_QUALIFIERS
from autogis.core.envmon.result_parser import QUALIFIER_FLAGS, STATUS_CODES

REPORT_MODULES = [
    "build_exceedance_event",
    "compliance_summary",
    "max_result_dataset",
    "qc_sample_summary",
    "regulatory_table_builder",
    "report_appendix_builder",
]


def _importer_nondetect_qualifiers():
    quals = {q for q, flags in QUALIFIER_FLAGS.items() if flags.get("is_nondetect")}
    quals |= {code for code, meaning in STATUS_CODES.items()
              if meaning == "NONDETECT"}
    return quals


def test_uj_is_in_the_canonical_set():
    assert "UJ" in ND_QUALIFIERS


def test_canonical_set_is_a_superset_of_the_importers_nondetect_qualifiers():
    """A result that imports as nondetect must also report as nondetect."""
    missing = _importer_nondetect_qualifiers() - ND_QUALIFIERS
    assert not missing, (
        f"result_parser.py treats {missing} as nondetect, but "
        f"core.common.config.ND_QUALIFIERS does not include them")


def test_all_seven_report_modules_import_the_canonical_set():
    import importlib

    for name in REPORT_MODULES:
        mod = importlib.import_module(f"autogis.core.envmon.{name}")
        assert mod.ND_QUALIFIERS is ND_QUALIFIERS, (
            f"{name}.ND_QUALIFIERS is not the shared "
            f"core.common.config.ND_QUALIFIERS object -- has it re-diverged "
            f"into a local copy?")


def test_soil_interval_selector_imports_the_canonical_set():
    from autogis.core.envmon import soil_interval_selector

    assert soil_interval_selector._ND_QUALIFIERS is ND_QUALIFIERS
