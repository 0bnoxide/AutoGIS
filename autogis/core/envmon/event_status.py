"""Event status & staleness checker (roadmap Phase 2, ADR-0093).

Read-only classification of each expected artifact of a monitoring event as
current / stale / missing / failed / awaiting-review, naming the upstream change
that caused the state. Pure and arcpy-free: it reads two append-only ledgers
(RunHistory, SourceRegistry) plus reviewer-comment rows, and hashes input files.

The freshness rule joins both ledgers (ADR-0093): an artifact is current only if
its producer ran, every declared input's current hash equals its latest accepted
baseline hash, that baseline predates the build, and no upstream artifact was
rebuilt at/after the build or is itself not-current. Same-second ties classify
stale (safe direction).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from ..common.run_history import RunHistory, RunRecord
from .source_registry import (
    SourceDocRecord,
    SourceRegistry,
    compute_sha256,
)

# --- state vocabulary -------------------------------------------------------

CURRENT = "current"
STALE = "stale"
MISSING = "missing"
FAILED = "failed"
AWAITING_REVIEW = "awaiting-review"

STATES = (CURRENT, STALE, MISSING, FAILED, AWAITING_REVIEW)

# Stable, documented exit codes for automation (ADR-0093). 1=internal error and
# 2=usage (Click-native) live outside this map.
STATE_EXIT_CODE = {
    CURRENT: 0,
    STALE: 3,
    MISSING: 4,
    FAILED: 5,
    AWAITING_REVIEW: 6,
}

# Worst-first. A failed build outranks a pending review; the report's exit code
# is the code of the worst state present by THIS order, not numeric max.
_PRECEDENCE = (FAILED, MISSING, STALE, AWAITING_REVIEW, CURRENT)


# --- dependency graph (hardcoded; tested as a matrix, ADR-0093) -------------

@dataclass(frozen=True)
class ArtifactSpec:
    kind: str                              # artifact + report label
    producer: str                          # run_history tool_name
    file_inputs: tuple[str, ...] = ()      # input kinds resolved by file hash
    upstream: tuple[str, ...] = ()         # upstream artifact kinds
    review: str = ""                       # "" | "reviewer-tracker" | "approved-model"


# Ordered so every artifact's upstream is classified before it.
DEPENDENCY_GRAPH: tuple[ArtifactSpec, ...] = (
    ArtifactSpec("canonical-import", "import-edd", ("workbook", "site-config")),
    ArtifactSpec("snapshot", "export-snapshot", (), ("canonical-import",)),
    ArtifactSpec("screening-evaluation", "apply-screening", ("screening",),
                 ("canonical-import",)),
    ArtifactSpec("figures", "export-figures", ("figure-spec",),
                 ("canonical-import",), review="reviewer-tracker"),
    ArtifactSpec("groundwater-surface", "run-gw-model-pipeline", (),
                 ("canonical-import",), review="approved-model"),
)

# The file-hash input kinds a caller must supply a path for.
FILE_INPUT_KINDS: tuple[str, ...] = tuple(
    dict.fromkeys(k for spec in DEPENDENCY_GRAPH for k in spec.file_inputs)
)


# --- result model -----------------------------------------------------------

@dataclass(frozen=True)
class ArtifactStatus:
    kind: str
    state: str
    producer: str
    causes: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"kind": self.kind, "state": self.state,
                "producer": self.producer, "causes": list(self.causes)}


@dataclass(frozen=True)
class EventStatusReport:
    site_id: str
    event_id: Optional[str]
    artifacts: tuple[ArtifactStatus, ...]
    schema: int = 1

    @property
    def summary(self) -> dict[str, int]:
        return {state: sum(a.state == state for a in self.artifacts)
                for state in STATES}

    @property
    def worst_state(self) -> str:
        present = {a.state for a in self.artifacts}
        for state in _PRECEDENCE:
            if state in present:
                return state
        return CURRENT

    def exit_code(self) -> int:
        return STATE_EXIT_CODE[self.worst_state]

    def as_dict(self) -> dict:
        return {
            "schema": self.schema,
            "site_id": self.site_id,
            "event_id": self.event_id,
            "artifacts": [a.as_dict() for a in self.artifacts],
            "summary": self.summary,
        }


# --- ledger helpers ---------------------------------------------------------

def _parse_dt(value: str) -> Optional[datetime]:
    """Parse a registry ISO timestamp; None if unparseable (treated as oldest)."""
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _latest_run(history: RunHistory, tool: str, site_id: str,
                event_id: Optional[str]) -> Optional[RunRecord]:
    """Latest run for (tool, site), honoring event scope.

    A run whose event_id is None is event-agnostic (many headless producers take
    no --event) and matches any event; an event-tagged run must match. Uses
    query()+manual filter, never latest() (which keys on tool+site only).
    """
    runs = history.query(site_id=site_id, tool_name=tool)
    if event_id is not None:
        runs = [r for r in runs if r.event_id in (None, event_id)]
    if not runs:
        return None
    return max(enumerate(runs), key=lambda ix: (ix[1].finished_at, ix[0]))[1]


def _latest_baseline(registry: SourceRegistry, site_id: str,
                     event_id: Optional[str],
                     kind: str) -> Optional[tuple[str, Optional[datetime]]]:
    """(sha256, registered_at) of the latest accepted baseline for a kind.

    Matched on kind (notes), not path — path equality is fragile across OS case
    and abs/rel drift. Append-only, so the last matching row is the latest.
    """
    rows = [r for r in registry.list_records(site_id=site_id, event_id=event_id)
            if r.notes == kind]
    if not rows:
        return None
    row = rows[-1]
    return row.sha256, _parse_dt(row.registered_at)


# --- classification ---------------------------------------------------------

def _stale_causes(spec: ArtifactSpec, built_at: datetime,
                  inputs: dict[str, Optional[Path]],
                  registry: SourceRegistry, site_id: str,
                  event_id: Optional[str],
                  states: dict[str, str],
                  runs: dict[str, Optional[RunRecord]]) -> list[str]:
    """Reasons this (already-built) artifact is stale; empty means fresh."""
    causes: list[str] = []

    for kind in spec.file_inputs:
        base = _latest_baseline(registry, site_id, event_id, kind)
        if base is None:
            causes.append(f"{kind}: no baseline (run event-status --accept)")
            continue
        base_sha, base_at = base
        path = inputs.get(kind)
        if path is None or not Path(path).exists():
            causes.append(f"{kind}: input file not found")
            continue
        if compute_sha256(Path(path)) != base_sha:
            causes.append(f"{kind} changed since baseline")
        elif base_at is not None and base_at >= built_at:
            # baseline re-accepted at/after the build: rebuild pending. >= so a
            # same-second tie is treated as pending (safe direction).
            causes.append(f"rebuild pending after re-baseline of {kind}")

    for up in spec.upstream:
        up_state = states.get(up)
        if up_state in (STALE, MISSING, FAILED):
            causes.append(f"upstream {up} is {up_state}")
            continue
        up_run = runs.get(up)
        # Strict >: an upstream naturally finishes before-or-with its dependent
        # in one pipeline, so a same-second co-build is current; only a build
        # strictly after this one is a rebuild. (The baseline clause above uses
        # >= because a baseline is accepted before a build, so same-second there
        # is anomalous.)
        if up_run is not None and up_run.finished_at > built_at:
            causes.append(f"upstream {up} rebuilt after this build")

    return causes


def _review_state(spec: ArtifactSpec, built_at: datetime,
                  history: RunHistory, site_id: str, event_id: Optional[str],
                  open_review_count: int) -> Optional[str]:
    """Awaiting-review overlay for an otherwise-current artifact, or None."""
    if spec.review == "reviewer-tracker":
        if open_review_count > 0:
            return f"{open_review_count} open reviewer comment(s)"
    elif spec.review == "approved-model":
        approve = _latest_run(history, "approve-gw-model", site_id, event_id)
        if approve is None or approve.finished_at < built_at:
            return "model run not yet approved"
    return None


def classify_event(*, site_id: str, event_id: Optional[str],
                   inputs: dict[str, Optional[Path]],
                   run_history: RunHistory, source_registry: SourceRegistry,
                   open_review_count: int = 0,
                   graph: Sequence[ArtifactSpec] = DEPENDENCY_GRAPH,
                   ) -> EventStatusReport:
    """Classify every artifact in the dependency graph for one event.

    ``inputs`` maps a file-input kind (see FILE_INPUT_KINDS) to the current file
    path (or None if not supplied). ``open_review_count`` is the number of OPEN/
    IN_REVIEW reviewer comments for this event's figures.
    """
    states: dict[str, str] = {}
    runs: dict[str, Optional[RunRecord]] = {}
    results: list[ArtifactStatus] = []

    for spec in graph:
        run = _latest_run(run_history, spec.producer, site_id, event_id)
        runs[spec.kind] = run

        if run is None:
            state, causes = MISSING, ("producer never ran",)
        elif run.status == "error":
            state = FAILED
            causes = (run.message or "producer run failed",)
        elif run.status == "cancelled":
            state, causes = MISSING, ("last producer run cancelled",)
        else:
            stale = _stale_causes(spec, run.finished_at, inputs, source_registry,
                                  site_id, event_id, states, runs)
            if stale:
                state, causes = STALE, tuple(stale)
            else:
                review = _review_state(spec, run.finished_at, run_history,
                                       site_id, event_id, open_review_count)
                if review is not None:
                    state, causes = AWAITING_REVIEW, (review,)
                else:
                    state, causes = CURRENT, ()

        states[spec.kind] = state
        results.append(ArtifactStatus(spec.kind, state, spec.producer, causes))

    return EventStatusReport(site_id, event_id, tuple(results))


# --- baseline acceptance (the only write path; registry rows, not prod data) --

def accept_baseline(*, site_id: str, event_id: Optional[str],
                    inputs: dict[str, Optional[Path]],
                    source_registry: SourceRegistry, now: str,
                    graph: Sequence[ArtifactSpec] = DEPENDENCY_GRAPH,
                    ) -> list[str]:
    """Register the current hash of each supplied file input as the baseline.

    ``now`` is the caller-supplied ISO timestamp (injected for testability).
    Returns a "kind=shortsha" line per registered input.
    """
    kinds = tuple(dict.fromkeys(k for spec in graph for k in spec.file_inputs))
    registered: list[str] = []
    for kind in kinds:
        path = inputs.get(kind)
        if path is None or not Path(path).exists():
            continue
        p = Path(path)
        sha = compute_sha256(p)
        source_registry.register(SourceDocRecord(
            registered_at=now,
            file_path=str(p),
            sha256=sha,
            file_size_bytes=p.stat().st_size,
            site_id=site_id,
            event_id=event_id or "",
            tool="event-status",
            notes=kind,
        ))
        registered.append(f"{kind}={sha[:8]}")
    return registered


# --- rendering --------------------------------------------------------------

def render_table(report: EventStatusReport) -> str:
    lines = [
        f"Event status  site={report.site_id}  event={report.event_id}",
        "",
        f"{'artifact':<22} {'state':<16} {'producer':<24} cause",
        "-" * 78,
    ]
    for a in report.artifacts:
        cause = "; ".join(a.causes)
        lines.append(f"{a.kind:<22} {a.state:<16} {a.producer:<24} {cause}")
    summary = report.summary
    lines += [
        "",
        "  ".join(f"{state}={summary[state]}" for state in STATES),
        f"worst: {report.worst_state} (exit {report.exit_code()})",
    ]
    return "\n".join(lines)
