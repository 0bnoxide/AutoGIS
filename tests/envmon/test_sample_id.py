"""Contract tests for the lifecycle SampleID single owner (sample_id.py)."""
import re
from datetime import datetime

import pytest

from autogis.core.envmon.sample_id import (
    PRIMARY, QC_SUFFIXES, SampleIdParts, build_sample_id, parse_sample_id,
    qc_class, strip_qc, xform_sample_id_calc,
)


def test_build_primary_from_datetime_and_compact_string_agree():
    dt = datetime(2026, 7, 15)
    assert build_sample_id("MW-1", dt, "GW") == "MW-1-20260715-GW"
    assert build_sample_id("MW-1", "20260715", "GW") == "MW-1-20260715-GW"


def test_build_rejects_non_compact_date_string():
    with pytest.raises(ValueError):
        build_sample_id("MW-1", "2026-07-15", "GW")


def test_build_parse_round_trip_across_matrices_and_qc():
    for matrix in ("GW", "SOIL", "SW", "SEDIMENT"):
        for suffix in QC_SUFFIXES:
            qc = suffix[1:].upper()
            sid = build_sample_id("MW-1", "20260715", matrix, qc=qc)
            assert parse_sample_id(sid) == SampleIdParts(
                "MW-1", "20260715", matrix, qc)


def test_every_qc_suffix_parses_to_its_declared_type():
    from autogis.core.envmon.qc_sample_summary import _infer_qc_type
    for suffix, qtype in QC_SUFFIXES.items():
        sid = build_sample_id("MW-1", "20260715", "GW", qc=suffix[1:].upper())
        assert _infer_qc_type(sid, "") == qtype


def test_nodate_form_shape_and_uniqueness():
    a = build_sample_id("MW-01", None, "GW")
    b = build_sample_id("MW-01", None, "GW")
    assert re.fullmatch(r"MW-01-NODATE-[0-9A-F]{6}-GW", a)
    assert a != b


def test_nodate_parses_with_empty_date_and_qc_populated():
    sid = build_sample_id("MW-01", None, "GW", qc="FD")
    parts = parse_sample_id(sid)
    assert parts is not None
    assert parts.date_compact == ""
    assert parts.matrix == "GW"
    assert parts.qc == "FD"


def test_primary_parse_has_empty_qc():
    assert parse_sample_id("MW-1-20260715-GW").qc == ""


def test_nodate_parses_when_location_ends_in_eight_digit_run():
    # dated regex matches first with an invalid rest; parser must fall
    # through to the NODATE form instead of returning None
    assert parse_sample_id("MW-20260101-NODATE-ABC123-GW") == SampleIdParts(
        "MW-20260101", "", "GW", "")


def test_dated_id_with_embedded_eight_digit_location_run_parses():
    assert parse_sample_id("MW-20260101-20260715-GW") == SampleIdParts(
        "MW-20260101", "20260715", "GW", "")


def test_non_lifecycle_identities_return_none():
    # sampling_plan form: {site}-{loc}-{event}-{group}
    assert parse_sample_id("H281-MW-1-2026Q3-VOCs") is None
    # legacy_migrator form: {loc}_{date_raw}_{row_idx}
    assert parse_sample_id("MW-1_2026-07-15_3") is None
    assert parse_sample_id("") is None


def test_planner_and_normalizer_agree_including_field_duplicate():
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.create_sampling_event import (
        build_sampling_event_plan)
    from autogis.core.envmon.normalize_survey123 import (
        normalize_survey123_submission)

    plan = build_sampling_event_plan(
        {"site_id": "H281", "site_name": "H281"},
        {
            "event_name": "Q3", "event_date": "2026-07-15",
            "coc_prefix": "H281", "lab_name": "Lab",
            "matrices": ["GW"], "location_ids": ["MW-1"],
            "crew_list": ["Alice"], "analyte_groups": {"VOCs": ["Benzene"]},
            "group_sampling": {}, "dup_frequency": 1,
        },
        {"Benzene": {}},
        run_id="RID",
    )
    planned = {r.sample_id for r in plan.expected_samples}

    def norm(payload):
        qa = QACollector()
        _, samp = normalize_survey123_submission(payload, "H281", "B1", qa)
        return samp[0]["SampleID"]

    primary = norm({"WellID": "MW-1", "SamplingDate": "2026-07-15",
                    "Matrix": "GW"})
    dup = norm({"WellID": "MW-1", "SamplingDate": "2026-07-15",
                "Matrix": "GW", "QAFlags": "field_dup"})
    assert planned == {primary, dup}
    assert dup == primary + "-FD"


def _eval_xform_calc(calc: str, well: str, date_compact: str, matrix: str,
                     is_dup: bool) -> str:
    """Evaluate the one XForm expression shape xform_sample_id_calc emits.

    Not a general evaluator — it understands exactly concat/format-date/
    if(selected(...)). That is the point: if the expression ever grows past
    this shape, this helper stops matching and forces a re-derivation instead
    of silently drifting from build_sample_id.
    """
    expr = calc
    expr = expr.replace('format-date(${SamplingDate}, "%Y%m%d")',
                        f'"{date_compact}"')
    expr = expr.replace("${WellID}", f'"{well}"')
    expr = expr.replace("${Matrix}", f'"{matrix}"')
    dup_leg = re.search(
        r'if\(selected\(\$\{QAFlags\}, "field_dup"\), "([^"]*)", "([^"]*)"\)',
        expr)
    assert dup_leg, f"unrecognized duplicate leg in {calc!r}"
    expr = expr[:dup_leg.start()] + \
        f'"{dup_leg.group(1) if is_dup else dup_leg.group(2)}"' + \
        expr[dup_leg.end():]
    body = re.fullmatch(r"concat\((.*)\)", expr)
    assert body, f"unrecognized calc shape in {calc!r}"
    return "".join(re.findall(r'"([^"]*)"', body.group(1)))


@pytest.mark.parametrize("is_dup", [False, True])
def test_xform_calc_renders_what_build_sample_id_renders(is_dup):
    """The Python and XForm renderings of LIFECYCLE_FORMAT agree.

    Couples the two for real: change build_sample_id's separator, field order
    or suffix and this fails. The old assertion compared the calc against a
    verbatim copy of its own return literal, which could not detect drift.
    """
    rendered = _eval_xform_calc(xform_sample_id_calc(), "MW-1", "20260715",
                                "GW", is_dup)
    assert rendered == build_sample_id("MW-1", "20260715", "GW",
                                       qc="FD" if is_dup else None)


def test_strip_qc_returns_the_primary_identity():
    assert strip_qc("MW-1-20260715-GW-FD") == "MW-1-20260715-GW"
    assert strip_qc("MW-1-20260715-GW-FD-A") == "MW-1-20260715-GW"
    # already primary, or not a lifecycle identity at all: unchanged
    assert strip_qc("MW-1-20260715-GW") == "MW-1-20260715-GW"
    assert strip_qc("H281-MW01-Q3-VOCs") == "H281-MW01-Q3-VOCs"
    assert strip_qc("") == ""


def test_strip_qc_round_trips_build_sample_id():
    for qc in ("FD", "MB", "LD-B"):
        assert strip_qc(build_sample_id("MW-1", "20260715", "GW", qc=qc)) == \
            build_sample_id("MW-1", "20260715", "GW")


@pytest.mark.parametrize("sample_id,expected", [
    ("MW-1-20260715-GW", PRIMARY),
    ("MW-1-20260715-GW-FD", "field_duplicate"),
    ("MW-1-20260715-GW-FD-A", "field_duplicate"),   # same class as -FD
    ("MW-1-20260715-GW-MB", "method_blank"),
    ("MW-1-20260715-GW-FB", "field_blank"),         # never folds into -MB
])
def test_qc_class_of_lifecycle_ids_comes_from_the_suffix(sample_id, expected):
    assert qc_class(sample_id) == expected


@pytest.mark.parametrize("sample_id", [
    "MW-1-20260715-GW-DUP", "MW-1-20260715-GW-D",
])
def test_qc_class_falls_back_to_profile_markers(sample_id):
    """Lab duplicates that are not lifecycle identities (issue #360)."""
    assert qc_class(sample_id, ["DUP", "-D", "FD"]) == "field_duplicate"


@pytest.mark.parametrize("sample_id", [
    "MW-1-DUP-20260715-GW",   # marker in the location segment: still parses,
    "MW-1DUP-20260715-GW",    # so the suffix is empty and only markers can
    "DUP-MW-1-20260715-GW",   # tell it apart from a primary
])
def test_qc_class_honours_a_marker_inside_the_location(sample_id):
    """table_normalizer matches markers against the location string, so this
    spelling is one the repo already expects. Classing it PRIMARY would let it
    fuzzy-consume the real primary — the exact defect the guard exists for."""
    assert qc_class(sample_id, ["DUP", "-D", "FD"]) == "field_duplicate"


def test_qc_class_suffix_beats_a_marker_in_the_location():
    """An explicit lifecycle suffix is authoritative over a location that
    merely happens to contain a marker substring."""
    assert qc_class("MW-1-DUP-20260715-GW-MB", ["DUP"]) == "method_blank"


def test_qc_class_does_not_invent_markers_that_are_not_configured():
    assert qc_class("MW-1-DUP-20260715-GW", ["ZZZ"]) == PRIMARY


def test_qc_class_is_none_when_there_is_no_signal():
    """None must not be read as 'primary' — the caller cannot know."""
    assert qc_class("H281-MW01-Q3-VOCs") is None      # sampling_plan identity
    assert qc_class("MW01_20260715_1") is None        # legacy_migrator identity
    assert qc_class("") is None


def test_every_qc_suffix_classes_as_its_declared_type():
    for suffix, qc_type in QC_SUFFIXES.items():
        sample_id = f"MW-1-20260715-GW{suffix.upper()}"
        assert qc_class(sample_id) == qc_type, suffix


def test_xform_calc_reads_the_adr_0021_qa_flag():
    """The duplicate leg reuses the qa_flags choice, not a second question."""
    calc = xform_sample_id_calc()
    assert 'selected(${QAFlags}, "field_dup")' in calc
    assert "IsFieldDup" not in calc
