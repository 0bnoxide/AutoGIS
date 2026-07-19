"""Pure report model and rendering for ArcGIS Pro qualification (ADR-0091)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


_OUTCOMES = ("pass", "fail", "skip")
_SELF_TEST_IDS = {"canary.parameter", "canary.scratch-gdb"}


@dataclass(frozen=True)
class Check:
    id: str
    outcome: str
    seconds: float = 0.0
    detail: str = ""

    def __post_init__(self):
        if self.outcome not in _OUTCOMES:
            raise ValueError(f"invalid qualification outcome: {self.outcome!r}")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "outcome": self.outcome,
            "seconds": round(self.seconds, 6),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class QualificationReport:
    environment: dict
    checks: tuple[Check, ...]
    schema: int = 1

    @property
    def summary(self) -> dict[str, int]:
        return {
            outcome: sum(check.outcome == outcome for check in self.checks)
            for outcome in _OUTCOMES
        }

    def as_dict(self) -> dict:
        return {
            "schema": self.schema,
            "environment": self.environment,
            "checks": [check.as_dict() for check in self.checks],
            "summary": self.summary,
        }


def qualification_exit_code(report: QualificationReport, *, self_test=False) -> int:
    if self_test:
        failures = {check.id for check in report.checks
                    if check.outcome == "fail"}
        return 0 if failures == _SELF_TEST_IDS and len(report.checks) == 2 else 1
    return 1 if report.summary["fail"] else 0


def render_markdown(report: QualificationReport) -> str:
    lines = ["# ArcGIS Pro qualification", "", "## Environment", ""]
    for key, value in sorted(report.environment.items()):
        rendered = json.dumps(value, sort_keys=True) if isinstance(value, dict) \
            else str(value)
        lines.append(f"- **{key}:** `{rendered}`")
    lines.extend([
        "", "## Checks", "", "| Check | Outcome | Seconds | Detail |",
        "|---|---:|---:|---|",
    ])
    for check in report.checks:
        detail = check.detail.replace("|", "\\|").replace("\n", "<br>")
        lines.append(
            f"| `{check.id}` | {check.outcome} | {check.seconds:.3f} | "
            f"{detail} |")
    summary = report.summary
    lines.extend([
        "", "## Summary", "",
        f"- Pass: {summary['pass']}",
        f"- Fail: {summary['fail']}",
        f"- Skip: {summary['skip']}",
        "",
        "Tier 1 and slice-1 Tier 2 do not execute tool bodies; defects inside "
        "execution seams remain outside this qualification slice.",
        "",
    ])
    return "\n".join(lines)


def write_report_files(report: QualificationReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "qualification.json"
    markdown_path = out_dir / "qualification.md"
    json_path.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path
