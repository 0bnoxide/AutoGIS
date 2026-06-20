"""QA record model, collector and report writers.

Every skipped/ambiguous/invalid item anywhere in the pipeline must create a
QARecord; nothing is silently dropped (spec: General rules).

Ported from envmon `qa_checks.py`. `QACollector` is made thread-safe: a
``threading.RLock`` guards every mutator AND every method that iterates
``self.records`` (deltas C6), so parallel downloads/imports cannot race.
"""
from __future__ import annotations

import csv
import json
import threading
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

SEV_INFO = "INFO"
SEV_WARNING = "WARNING"
SEV_ERROR = "ERROR"
SEV_CRITICAL = "CRITICAL"
_SEV_ORDER = {SEV_INFO: 0, SEV_WARNING: 1, SEV_ERROR: 2, SEV_CRITICAL: 3}


@dataclass
class QARecord:
    severity: str
    category: str
    message: str
    recommended_action: str = ""
    site_id: str = ""
    location_id: str = ""
    sample_id: str = ""
    sample_date: str = ""
    analyte_name: str = ""
    source_workbook: str = ""
    source_sheet: str = ""
    source_row: Optional[int] = None
    source_column: str = ""
    source_cell: str = ""
    import_batch_id: str = ""

    def as_gdb_row(self) -> dict:
        d = asdict(self)
        return {
            "ImportBatchID": d["import_batch_id"], "Severity": d["severity"],
            "Category": d["category"], "SiteID": d["site_id"],
            "LocationID": d["location_id"], "SampleID": d["sample_id"],
            "SampleDate": d["sample_date"], "AnalyteName": d["analyte_name"],
            "Message": d["message"], "RecommendedAction": d["recommended_action"],
            "SourceWorkbook": d["source_workbook"], "SourceSheet": d["source_sheet"],
            "SourceRow": d["source_row"], "SourceColumn": d["source_column"],
            "SourceCell": d["source_cell"],
        }


@dataclass
class QACollector:
    records: List[QARecord] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock,
                                   repr=False, compare=False)

    def add(self, severity, category: str = "", message: str = "",
            **kw) -> QARecord:
        """Add a record. Accepts either positional fields or a QARecord."""
        if isinstance(severity, QARecord):
            with self._lock:
                self.records.append(severity)
            return severity
        rec = QARecord(severity=severity, category=category, message=message, **kw)
        with self._lock:
            self.records.append(rec)
        return rec

    def extend(self, recs: Iterable[QARecord]) -> None:
        with self._lock:
            self.records.extend(recs)

    def counts(self) -> dict:
        return dict(self.counts_by_severity())

    def counts_by_severity(self) -> Counter:
        with self._lock:
            return Counter(r.severity for r in self.records)

    def counts_by_category(self) -> Counter:
        with self._lock:
            return Counter((r.severity, r.category) for r in self.records)

    def has_blocking(self, allow_warnings: bool = True,
                     allow_errors: bool = False) -> bool:
        with self._lock:
            worst = max((_SEV_ORDER[r.severity] for r in self.records), default=-1)
        if worst >= _SEV_ORDER[SEV_CRITICAL]:
            return True
        if worst >= _SEV_ORDER[SEV_ERROR] and not allow_errors:
            return True
        if worst >= _SEV_ORDER[SEV_WARNING] and not allow_warnings:
            return True
        return False

    def status(self, allow_warnings: bool = True,
               allow_errors: bool = False) -> str:
        return ("FAIL" if self.has_blocking(allow_warnings, allow_errors)
                else "PASS")

    # ---- report writers -------------------------------------------------
    def write_csv(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = list(asdict(QARecord("", "", "")).keys())
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            with self._lock:
                for r in self.records:
                    w.writerow(asdict(r))
        return path

    def write_json_summary(self, path: Path, extra: Optional[dict] = None) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            summary = {
                "generated": datetime.now().isoformat(timespec="seconds"),
                "status": self.status(),
                "counts_by_severity": dict(self.counts_by_severity()),
                "counts_by_category": {
                    f"{sev}/{cat}": n
                    for (sev, cat), n in self.counts_by_category().items()
                },
                "record_count": len(self.records),
            }
        if extra:
            summary["extra"] = extra
        path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return path

    def write_markdown(self, path: Path, title: str = "QA Report") -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"# {title}", "",
                 f"Generated: {datetime.now().isoformat(timespec='seconds')}",
                 f"Overall status: **{self.status()}**", "", "## Counts", ""]
        for sev in (SEV_CRITICAL, SEV_ERROR, SEV_WARNING, SEV_INFO):
            lines.append(f"- {sev}: {self.counts_by_severity().get(sev, 0)}")
        lines += ["", "## Records", ""]
        with self._lock:
            ordered = sorted(self.records, key=lambda r: -_SEV_ORDER[r.severity])
        for r in ordered:
            loc = " ".join(x for x in (r.source_sheet, r.source_cell or
                           (f"row {r.source_row}" if r.source_row else "")) if x)
            lines.append(f"- **{r.severity}** [{r.category}] {r.message}"
                         + (f" ({loc})" if loc else "")
                         + (f" -> {r.recommended_action}" if r.recommended_action else ""))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
