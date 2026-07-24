"""lab_qa_trends.py — longitudinal laboratory-QA trending (Phase 7, slice 1).

Headless, arcpy-free. Consumes a multi-event export of lab-QC results
(``QCResultRecord`` rows, i.e. the ``Env_QCResults`` table serialized to CSV via
``records_csv``) and computes deterministic QA trends grouped by method, matrix,
and analyte:

- **Recovery** — surrogate / spike / LCS percent-recovery outside acceptance
  limits. Membership is data-driven: any QC row carrying a ``PercentRecovery``
  participates. Row-level ``RecoveryLowerLimit``/``RecoveryUpperLimit`` from the
  lab EDD take precedence; a cited, configurable default window is the fallback.
- **Blank** — method/field/trip/equipment blanks reporting a detection at or
  above the reporting limit (RL), configurable as a multiple of RL.

Every trend row carries the threshold applied *and its citation* (roadmap Phase 7
gate: thresholds "configurable, cited, and represented in QA output"). The tool
reports frequencies deterministically; it does not automate professional
data-validation conclusions.

Slice-1 boundaries (see ADR): the other three roadmap dimensions (duplicate RPD,
reporting-limit changes, qualifier frequency) are additive later slices;
"by laboratory" grouping is deferred because ``Env_QCResults`` carries no
``LabName`` column (regular results do, on ``Env_AnalyticalResults``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, List, Optional, Sequence

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING


# ---------------------------------------------------------------------------
# Thresholds (configurable + cited)
# ---------------------------------------------------------------------------

@dataclass
class LabQAThresholds:
    """Configurable QA thresholds with citations. Overridable from a config
    dict/YAML; lab-provided per-row limits always take precedence over these."""
    recovery_default_lower: float = 70.0
    recovery_default_upper: float = 130.0
    recovery_citation: str = (
        "Default 70-130% recovery window (common USEPA SW-846 / NFG project "
        "default); row RecoveryLowerLimit/UpperLimit from the lab EDD take "
        "precedence when present.")
    # A blank is "detected" when ResultNumeric >= blank_rl_multiple * RL.
    blank_rl_multiple: float = 1.0
    blank_citation: str = (
        "Blank flagged as a detection when result >= RL (blank_rl_multiple x "
        "reporting limit); a clean method blank should be < RL per USEPA QC "
        "guidance. Set blank_rl_multiple=0.5 for programs using 1/2-RL.")
    # QCType values (case-insensitive) treated as blanks. Substring 'BLANK'
    # also matches, so lab-specific codes like 'MB'/'FB'/'TB'/'EB' plus any
    # '*BLANK*' spelling are covered without enumerating every dialect.
    blank_qc_types: frozenset = frozenset(
        {"MB", "FB", "TB", "EB", "METHOD BLANK", "FIELD BLANK",
         "TRIP BLANK", "EQUIPMENT BLANK", "EQUIPMENT RINSATE"})

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "LabQAThresholds":
        """Build from a partial override dict (unknown keys ignored)."""
        base = cls()
        if not data:
            return base
        if (
            {"recovery_default_lower", "recovery_default_upper"} & data.keys()
            and "recovery_citation" not in data
        ):
            raise ValueError(
                "recovery_citation is required when overriding the default "
                "recovery window")
        for k, v in data.items():
            if k == "blank_qc_types" and v is not None:
                setattr(base, k, frozenset(str(x).upper() for x in v))
            elif hasattr(base, k):
                setattr(base, k, v)
        return base

    def is_blank(self, qc_type: str) -> bool:
        t = (qc_type or "").strip().upper()
        return t in self.blank_qc_types or "BLANK" in t


# ---------------------------------------------------------------------------
# Output row
# ---------------------------------------------------------------------------

@dataclass
class LabQATrendRow:
    """One trend summary per (metric, matrix, method, analyte) group. Field
    names are CSV column names (round-trips via records_csv)."""
    table_name: ClassVar[str] = "LabQA_Trends"
    metric: str                 # "recovery" | "blank"
    matrix: str
    method_id: str
    analyte: str
    n_total: int                # QC results considered in this group
    n_flagged: int              # out-of-limit recoveries / blank detections
    flag_rate: float            # n_flagged / n_total, rounded 4dp
    date_first: str             # ISO date of earliest QC result (or "")
    date_last: str              # ISO date of latest QC result (or "")
    threshold_applied: str      # human-readable threshold used
    citation: str               # source/standard for the threshold
    worst_sample_id: str = ""   # example driving the flag (worst offender)
    worst_value: Optional[float] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _analyte_key(row) -> str:
    return (getattr(row, "AnalyteCanonicalName", "") or "").strip() \
        or (getattr(row, "AnalyteName", "") or "").strip()


def _group_key(row):
    return ((row.Matrix or "").strip(),
            (row.MethodID or "").strip(),
            _analyte_key(row))


def _iso(d) -> str:
    return d.isoformat() if d is not None else ""


def _date_span(rows) -> tuple[str, str]:
    dates = [r.AnalysisDate for r in rows if r.AnalysisDate is not None]
    if not dates:
        return "", ""
    return _iso(min(dates)), _iso(max(dates))


def _rate(flagged: int, total: int) -> float:
    return round(flagged / total, 4) if total else 0.0


# ---------------------------------------------------------------------------
# Recovery trend
# ---------------------------------------------------------------------------

def compute_recovery_trends(
    rows: Sequence,
    thresholds: LabQAThresholds,
    qa: Optional[QACollector] = None,
) -> List[LabQATrendRow]:
    """Frequency of out-of-limit percent recoveries per method/matrix/analyte.

    A row participates iff it carries a ``PercentRecovery`` (data-driven — this
    is exactly the set of recovery-bearing QC types: surrogates, LCS/LCSD,
    MS/MSD, CCV/ICV)."""
    if qa is None:
        qa = QACollector()
    groups: dict = {}
    for r in rows:
        if r.PercentRecovery is None:
            continue
        groups.setdefault(_group_key(r), []).append(r)

    out: List[LabQATrendRow] = []
    for (matrix, method, analyte), grp in sorted(groups.items()):
        flagged = []
        worst = None  # (distance_outside, sample_id, recovery)
        windows = set()
        used_default = False
        used_lab_limits = False
        for r in grp:
            lower = r.RecoveryLowerLimit if r.RecoveryLowerLimit is not None \
                else thresholds.recovery_default_lower
            upper = r.RecoveryUpperLimit if r.RecoveryUpperLimit is not None \
                else thresholds.recovery_default_upper
            windows.add((lower, upper))
            used_default |= (
                r.RecoveryLowerLimit is None or r.RecoveryUpperLimit is None)
            used_lab_limits |= (
                r.RecoveryLowerLimit is not None
                or r.RecoveryUpperLimit is not None)
            rec = r.PercentRecovery
            if rec < lower or rec > upper:
                flagged.append(r)
                dist = (lower - rec) if rec < lower else (rec - upper)
                if worst is None or dist > worst[0]:
                    worst = (dist, r.SampleID, rec)
        first, last = _date_span(grp)
        window_text = ", ".join(
            f"[{lower:g}, {upper:g}]%" for lower, upper in sorted(windows))
        citations = []
        if used_default:
            citations.append(thresholds.recovery_citation)
        if used_lab_limits:
            citations.append(
                "Lab EDD RecoveryLowerLimit/RecoveryUpperLimit values supplied "
                "on the input rows.")
        out.append(LabQATrendRow(
            metric="recovery", matrix=matrix, method_id=method, analyte=analyte,
            n_total=len(grp), n_flagged=len(flagged),
            flag_rate=_rate(len(flagged), len(grp)),
            date_first=first, date_last=last,
            threshold_applied=f"recovery within {window_text}",
            citation=" ".join(citations),
            worst_sample_id=worst[1] if worst else "",
            worst_value=worst[2] if worst else None,
        ))
    qa.add(SEV_INFO, "recovery_trends",
           f"recovery trends: {len(out)} method/matrix/analyte group(s)")
    return out


# ---------------------------------------------------------------------------
# Blank trend
# ---------------------------------------------------------------------------

def compute_blank_trends(
    rows: Sequence,
    thresholds: LabQAThresholds,
    qa: Optional[QACollector] = None,
) -> List[LabQATrendRow]:
    """Frequency of blank detections (result >= multiple x RL) per group."""
    if qa is None:
        qa = QACollector()
    groups: dict = {}
    for r in rows:
        if thresholds.is_blank(r.QCType):
            groups.setdefault(_group_key(r), []).append(r)

    out: List[LabQATrendRow] = []
    for (matrix, method, analyte), grp in sorted(groups.items()):
        flagged = []
        worst = None  # (result, sample_id)
        for r in grp:
            if r.ResultNumeric is None or r.IsNonDetect:
                continue
            if r.ReportingLimit is None:
                # No RL to compare against — a positive result is still a
                # detection, but flag the ambiguity rather than guess a limit.
                qa.add(SEV_WARNING, "blank_no_rl",
                       f"Blank {r.SampleID!r} ({analyte}) has a result but no "
                       f"reporting limit; counted as detected.",
                       sample_id=r.SampleID)
                threshold_met = r.ResultNumeric > 0
            else:
                threshold_met = (r.ResultNumeric
                                 >= thresholds.blank_rl_multiple * r.ReportingLimit)
            if threshold_met:
                flagged.append(r)
                if worst is None or r.ResultNumeric > worst[0]:
                    worst = (r.ResultNumeric, r.SampleID)
        first, last = _date_span(grp)
        out.append(LabQATrendRow(
            metric="blank", matrix=matrix, method_id=method, analyte=analyte,
            n_total=len(grp), n_flagged=len(flagged),
            flag_rate=_rate(len(flagged), len(grp)),
            date_first=first, date_last=last,
            threshold_applied=(
                f"blank detected when result >= "
                f"{thresholds.blank_rl_multiple:g} x RL"),
            citation=thresholds.blank_citation,
            worst_sample_id=worst[1] if worst else "",
            worst_value=worst[0] if worst else None,
        ))
    qa.add(SEV_INFO, "blank_trends",
           f"blank trends: {len(out)} method/matrix/analyte group(s)")
    return out


def compute_lab_qa_trends(
    rows: Sequence,
    thresholds: Optional[LabQAThresholds] = None,
    qa: Optional[QACollector] = None,
) -> List[LabQATrendRow]:
    """Recovery + blank trends, sorted by (metric, matrix, method, analyte)."""
    if thresholds is None:
        thresholds = LabQAThresholds()
    if qa is None:
        qa = QACollector()
    out = (compute_recovery_trends(rows, thresholds, qa)
           + compute_blank_trends(rows, thresholds, qa))
    return sorted(out, key=lambda t: (t.metric, t.matrix, t.method_id, t.analyte))


# ---------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------

def _demo() -> None:
    from datetime import date
    from ..envmon.gdb_schema import QCResultRecord

    def qc(qctype, analyte, *, rec=None, lo=None, hi=None, result=None,
           rl=None, nd=0, sid="S", d=None, method="8260", matrix="GW"):
        return QCResultRecord(
            ImportBatchID="B", SiteID="SITE", Matrix=matrix, SampleID=sid,
            QCType=qctype, AnalyteName=analyte, AnalyteCanonicalName=analyte,
            SourceWorkbook="w", SourceSheet="s", SourceRow=1, MethodID=method,
            AnalysisDate=d, ResultNumeric=result, ReportingLimit=rl,
            IsNonDetect=nd, PercentRecovery=rec,
            RecoveryLowerLimit=lo, RecoveryUpperLimit=hi)

    rows = [
        # recovery: 2 surrogates, one out (55% < default 70), one in (95%)
        qc("SURROGATE", "Toluene", rec=55.0, sid="R1", d=date(2026, 1, 1)),
        qc("SURROGATE", "Toluene", rec=95.0, sid="R2", d=date(2026, 2, 1)),
        # recovery with lab limits overriding default: 60% within [50,150] => OK
        qc("LCS", "Benzene", rec=60.0, lo=50.0, hi=150.0, sid="R3", d=date(2026, 1, 15)),
        # blanks: one detected (>= RL), one clean (nd), one below RL
        qc("MB", "Benzene", result=2.0, rl=1.0, sid="B1", d=date(2026, 1, 1)),
        qc("MB", "Benzene", result=None, rl=1.0, nd=1, sid="B2", d=date(2026, 2, 1)),
        qc("Method Blank", "Benzene", result=0.4, rl=1.0, sid="B3", d=date(2026, 3, 1)),
    ]
    t = LabQAThresholds()
    trends = compute_lab_qa_trends(rows, t)

    rec_tol = next(x for x in trends if x.metric == "recovery" and x.analyte == "Toluene")
    assert rec_tol.n_total == 2 and rec_tol.n_flagged == 1
    assert rec_tol.worst_sample_id == "R1"
    assert rec_tol.date_first == "2026-01-01" and rec_tol.date_last == "2026-02-01"

    rec_benz = next(x for x in trends if x.metric == "recovery" and x.analyte == "Benzene")
    assert rec_benz.n_flagged == 0  # 60% inside lab window [50,150]

    blank = next(x for x in trends if x.metric == "blank" and x.analyte == "Benzene")
    assert blank.n_total == 3 and blank.n_flagged == 1  # only B1 (2.0 >= 1.0)
    assert blank.worst_sample_id == "B1"

    # blank_rl_multiple override: 0.5*RL=0.5, so B3 (0.4) still clean, B1 flagged
    t2 = LabQAThresholds.from_dict({"blank_rl_multiple": 0.5})
    blank2 = next(x for x in compute_blank_trends(rows, t2)
                  if x.analyte == "Benzene")
    assert blank2.n_flagged == 1

    print("lab_qa_trends _demo OK")


if __name__ == "__main__":
    _demo()
