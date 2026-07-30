"""report_input.py — shared input guards for the headless report family.

The report-family builders (max-result dataset, compliance table, exceedance
event, appendix, regulatory table, QC summary, soil intervals, trend charts)
consume plain ``csv.DictReader`` dicts rather than ``AnalyticalResultRecord``
dataclasses. Two silent-wrong-answer defects came out of that:

- **#339** — those builders hard-coded a second column vocabulary
  (``ResultValue``/``ResultQualifier``/``ReportedUnits``) that nothing in the
  pipeline actually produces. Feeding them the canonical CSV every sibling
  command emits made a detected result read as a nondetect, or dropped the
  row entirely, with no error and no QA record.
- **#376** — date filters compared the raw option text against the raw
  ``SampleDate`` text, so a typo'd ``--date-from`` sorted before every real
  ISO date and silently filtered out every row, exit 0.

Both helpers are arcpy-free and operate on plain dicts/strings.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Sequence

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING

#: Report-family column name -> canonical ``AnalyticalResultRecord`` field.
#: The report vocabulary stays the one the builders read, so this is a
#: widening (accept both), not a rename.
REPORT_FIELD_ALIASES: Dict[str, str] = {
    "ResultValue": "ResultNumeric",
    "ResultQualifier": "Qualifier",
    "ReportedUnits": "Units",
}


def _blank(value) -> bool:
    return value is None or str(value).strip() == ""


def normalize_report_rows(rows: Sequence[dict],
                          qa: Optional[QACollector] = None) -> List[dict]:
    """Return *rows* with report-vocabulary keys backfilled from their
    canonical equivalents wherever the report key is absent or blank.

    Rows already in the report vocabulary pass through unchanged, so this is
    safe to apply unconditionally at a builder's entry point. Input dicts are
    never mutated; a row needing no backfill is returned as-is.

    A row set carrying *neither* vocabulary is the genuinely broken input that
    used to fail silently — it gets a QA WARNING rather than being coerced.
    """
    rows = list(rows)
    if not rows:
        return rows

    present = {k for r in rows if isinstance(r, dict) for k in r}
    # Only the aliases whose canonical source is actually present can do any
    # work. When that set is empty -- the overwhelmingly common case of input
    # already in the report vocabulary -- nothing is copied and the caller's
    # own dicts are handed straight back.
    active = {rep: can for rep, can in REPORT_FIELD_ALIASES.items()
              if can in present}
    out = [dict(r) if isinstance(r, dict) else r for r in rows] if active \
        else rows

    substituted: set = set()
    for report_name, canonical_name in active.items():
        for r in out:
            if isinstance(r, dict) and _blank(r.get(report_name)) \
                    and not _blank(r.get(canonical_name)):
                r[report_name] = r[canonical_name]
                substituted.add(report_name)

    if qa is not None:
        if substituted:
            qa.add(SEV_INFO, "result_vocabulary_normalized",
                   "Canonical result columns were read for "
                   f"{sorted(substituted)}; the report vocabulary "
                   f"({', '.join(sorted(REPORT_FIELD_ALIASES))}) was absent "
                   "or blank for those fields.")
        elif not (present & set(REPORT_FIELD_ALIASES)):
            qa.add(SEV_WARNING, "result_vocabulary_unrecognized",
                   "Input rows carry neither the report vocabulary "
                   f"({', '.join(sorted(REPORT_FIELD_ALIASES))}) nor the "
                   "canonical one "
                   f"({', '.join(sorted(REPORT_FIELD_ALIASES.values()))}); "
                   "every result will read as an unparseable nondetect. "
                   "Check that this CSV is an analytical-results export.")
    return out


def validate_iso_date(value: Optional[str], option: str) -> Optional[str]:
    """Return *value* unchanged, or raise ``ValueError`` if it is not a
    well-formed ``YYYY-MM-DD`` date.

    Round-trip equality is the check, not just ``fromisoformat`` success:
    since 3.11 that accepts basic forms like ``20260701`` which parse fine but
    compare wrong against the hyphenated ``SampleDate`` text these filters are
    matched against lexicographically.
    """
    if value is None or value == "":
        return value
    text = str(value)
    try:
        ok = date.fromisoformat(text).isoformat() == text
    except ValueError:
        ok = False
    if not ok:
        raise ValueError(
            f"{option}: {text!r} is not a valid ISO date (YYYY-MM-DD). "
            "Date filters compare against SampleDate as text, so a malformed "
            "value silently matches no rows instead of failing.")
    return value
