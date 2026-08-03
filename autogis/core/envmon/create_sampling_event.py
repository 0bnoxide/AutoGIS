"""create_sampling_event.py — pre-field sampling event planner.

Headless (arcpy-free, openpyxl-free). Pure stdlib + the existing
load_config loader.  Outputs a SamplingEventPlan that the writer
module serialises to XLSX.

Design decisions:
- run_id and event_date injected as parameters for deterministic tests.
- analyte_groups stays as {group: [names]} (form-builder contract; ADR-0021).
- group_sampling is a separate additive section for container/preservative/hold_time.
- dup_frequency: 1 FD well per N wells, 0-based position: wells at 1-based
  positions [N, 2N, 3N, …] receive field duplicates.
- Trip/equipment blanks: non-goal for v1.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from ..common.config import load_config
from .sample_id import build_sample_id


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ExpectedSampleRow:
    sample_id: str
    location_id: str
    event_date: str         # ISO "YYYY-MM-DD"
    matrix: str
    analyte_group: str
    sample_type: str        # "Regular" or "Field Duplicate"
    container_type: str
    preservative: str
    hold_time_hr: int
    bottle_count: int
    coc_number: str
    assigned_to: str


@dataclass
class CrewAssignmentRow:
    location_id: str
    assigned_to: str
    bottle_count: int       # total bottles at this well across all groups


@dataclass
class SamplingEventPlan:
    event_name: str
    event_date: str
    site_id: str
    site_name: str
    lab_name: str
    coc_prefix: str
    run_id: str
    expected_samples: List[ExpectedSampleRow]
    crew_assignments: List[CrewAssignmentRow]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _date_to_yyyymmdd(iso_date: str) -> str:
    """'2026-07-15' → '20260715'."""
    m = _ISO_RE.match(iso_date.strip())
    if not m:
        raise ValueError(
            f"event_date must be ISO format YYYY-MM-DD, got: {iso_date!r}")
    return m.group(1) + m.group(2) + m.group(3)


def _coc_number(prefix: str, seq: int) -> str:
    return f"{prefix}-{seq:03d}"


def _round_robin(items: List[str], crew: List[str]) -> Dict[str, str]:
    """Assign each item to a crew member in round-robin order."""
    return {item: crew[i % len(crew)] for i, item in enumerate(items)}


def _dup_wells(location_ids: List[str], dup_frequency: int) -> set:
    """Return the set of location_ids that should receive field duplicates.

    With dup_frequency=N, the Nth, 2Nth, … (1-based) wells get a dup.
    """
    if dup_frequency <= 0:
        return set()
    return {loc for i, loc in enumerate(location_ids, start=1)
            if i % dup_frequency == 0}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_event_config(path: Path) -> dict:
    """Load and return an event config dict from YAML or JSON."""
    return load_config(Path(path))


def build_sampling_event_plan(
    site_config_dict: dict,
    event_config: dict,
    analyte_dict: dict,
    *,
    run_id: str,
) -> SamplingEventPlan:
    """Build a SamplingEventPlan from site + event + analyte configs.

    Parameters
    ----------
    site_config_dict:
        Dict with at least ``site_id`` and ``site_name``.
        Pass ``SiteConfig.data`` when you have a loaded SiteConfig.
    event_config:
        Dict loaded from the event YAML. Required keys: event_name,
        event_date, coc_prefix, lab_name, matrices, location_ids,
        crew_list, analyte_groups, group_sampling.
        Optional key: dup_frequency (default 10; 0 = none).
    analyte_dict:
        Dict returned by ``load_analyte_dictionary()``. Every analyte name
        listed in ``event_config["analyte_groups"]`` is validated against
        this dict — raises ``ValueError`` if any analyte is unknown. This
        catches misspellings before the crew reaches the field.
    run_id:
        Caller-supplied UUID string (inject for tests; use
        ``str(uuid.uuid4())`` in production callers).
    """
    # ── required keys ──
    event_name: str = event_config["event_name"]
    event_date: str = event_config["event_date"]
    coc_prefix: str = event_config["coc_prefix"]
    lab_name: str = event_config.get("lab_name", "")
    matrices: List[str] = event_config.get("matrices", ["GW"])
    location_ids: List[str] = event_config.get("location_ids", [])
    crew_list: List[str] = event_config.get("crew_list", [])
    analyte_groups: Dict[str, List[str]] = event_config.get("analyte_groups", {})
    group_sampling: Dict[str, dict] = event_config.get("group_sampling", {})
    dup_frequency: int = int(event_config.get("dup_frequency", 10))

    if not location_ids:
        raise ValueError("event_config must have at least one entry in location_ids")
    if not crew_list:
        raise ValueError("event_config must have at least one entry in crew_list")

    # A scalar under a group (``VOC: Benzene`` instead of ``VOC: [Benzene]``)
    # used to skip the analyte-dictionary check entirely and ship an
    # unvalidated group (issue #437) -- reject the shape before validating.
    bad_shape = sorted(
        str(group) for group, names in analyte_groups.items()
        if not isinstance(names, (list, tuple))
    )
    if bad_shape:
        raise ValueError(
            f"analyte_groups values must be lists of analyte names; got a "
            f"non-list value for group(s): {', '.join(bad_shape)}"
        )

    # Validate every analyte in analyte_groups exists in analyte_dict
    unknown = {
        analyte
        for names in analyte_groups.values()
        for analyte in names
        if analyte not in analyte_dict
    }
    if unknown:
        raise ValueError(
            f"Unknown analyte(s) in analyte_groups (not in analyte_dict): "
            f"{', '.join(sorted(unknown))}"
        )

    site_id: str = site_config_dict.get("site_id", "SITE")
    site_name: str = site_config_dict.get("site_name", site_id)

    date_compact = _date_to_yyyymmdd(event_date)
    # Only the first matrix has ever reached the plan; the rest were dropped
    # with no signal, so a crew was sent out with no bottles for them and the
    # gap only resurfaced as lab-side `matrix_mismatch` errors (issue #421).
    # There is no per-analyte-group matrix mapping in the event schema to
    # build a correct multi-matrix plan from, so refuse rather than guess.
    if len(matrices) > 1:
        raise ValueError(
            f"event_config declares {len(matrices)} matrices "
            f"({', '.join(str(m) for m in matrices)}) but a sampling-event "
            f"plan covers exactly one; only {matrices[0]!r} would be planned "
            f"and the rest silently dropped. Use one event config per matrix."
        )
    primary_matrix = matrices[0] if matrices else "GW"
    crew_map = _round_robin(location_ids, crew_list)
    dup_set = _dup_wells(location_ids, dup_frequency)

    expected_samples: List[ExpectedSampleRow] = []
    crew_bottle_totals: Dict[str, int] = {loc: 0 for loc in location_ids}

    for seq, location_id in enumerate(location_ids, start=1):
        coc_num = _coc_number(coc_prefix, seq)
        assigned = crew_map[location_id]
        is_dup_well = location_id in dup_set

        for group_name, _analyte_names in analyte_groups.items():
            sampling_meta = group_sampling.get(group_name, {})
            container = sampling_meta.get("container", "")
            preservative = sampling_meta.get("preservative", "")
            hold_time_hr = int(sampling_meta.get("hold_time_hr", 0))
            bottles = int(sampling_meta.get("bottles", 1))

            # Primary sample
            expected_samples.append(ExpectedSampleRow(
                sample_id=build_sample_id(location_id, date_compact,
                                          primary_matrix),
                location_id=location_id,
                event_date=event_date,
                matrix=primary_matrix,
                analyte_group=group_name,
                sample_type="Regular",
                container_type=container,
                preservative=preservative,
                hold_time_hr=hold_time_hr,
                bottle_count=bottles,
                coc_number=coc_num,
                assigned_to=assigned,
            ))
            crew_bottle_totals[location_id] += bottles

            # Field duplicate (counts as real bottles for crew logistics)
            if is_dup_well:
                expected_samples.append(ExpectedSampleRow(
                    sample_id=build_sample_id(location_id, date_compact,
                                              primary_matrix, qc="FD-A"),
                    location_id=location_id,
                    event_date=event_date,
                    matrix=primary_matrix,
                    analyte_group=group_name,
                    sample_type="Field Duplicate",
                    container_type=container,
                    preservative=preservative,
                    hold_time_hr=hold_time_hr,
                    bottle_count=bottles,
                    coc_number=coc_num,
                    assigned_to=assigned,
                ))
                crew_bottle_totals[location_id] += bottles

    crew_assignments = [
        CrewAssignmentRow(
            location_id=loc,
            assigned_to=crew_map[loc],
            bottle_count=crew_bottle_totals[loc],
        )
        for loc in location_ids
    ]

    return SamplingEventPlan(
        event_name=event_name,
        event_date=event_date,
        site_id=site_id,
        site_name=site_name,
        lab_name=lab_name,
        coc_prefix=coc_prefix,
        run_id=run_id,
        expected_samples=expected_samples,
        crew_assignments=crew_assignments,
    )
