"""Tool 6.4 RefreshMonitoringDashboardData.

Push the local dashboard data-mart tables (``Dash_*``, computed by
``dashboard_data_mart.py`` / Tool 6.7) to their hosted AGOL feature layers
via truncate-and-append. Injected ``gis`` only (same contract as
``publish.py``) -- every arcgis object here (item, layer, manager) comes
through the caller-supplied ``gis``, so this module never imports ``arcgis``
itself and works with the cloud extra absent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING, SEV_ERROR


@dataclass
class RefreshResult:
    tables_refreshed: int = 0
    rows_pushed: Dict[str, int] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)
    qa: QACollector = field(default_factory=QACollector)


def _field_names(layer) -> set:
    """Hosted layer field names; tolerant of dict-like or attribute-style fields
    (arcgis ``PropertyMap`` supports both, so this also accepts plain dicts in
    tests)."""
    names = set()
    for f in layer.properties.fields:
        name = f["name"] if isinstance(f, dict) else getattr(f, "name", None)
        if name:
            names.add(name)
    return names


# Truncate-and-append is destructive with no transaction: once truncate()
# lands, a failed or partial append leaves the hosted table empty or
# incomplete. There is nothing to roll back *to* on the service -- but the
# local mart is the full source of truth and the refresh rebuilds each table
# from it, so re-running after fixing the rejected rows is the recovery path
# (issue #428). Stated in the QA record so an operator reading the report
# knows the hosted state and what to do about it.
_RECOVERY = ("Re-run this command after fixing the rejected rows: the local "
             "mart holds every row and the refresh rebuilds the table from it.")


def _rejected_adds(response) -> List[dict]:
    """Add results the service rejected.

    ArcGIS edit APIs report per-feature failures *inside* a normal response
    rather than raising, so treating any non-raising ``edit_features()`` call
    as success let a partial append be counted as a refreshed table (#428).
    A response shape we don't recognize is treated as "nothing rejected" --
    the raising path still covers a hard failure.
    """
    if not hasattr(response, "get"):
        return []
    return [r for r in (response.get("addResults") or [])
            if hasattr(r, "get") and not r.get("success", True)]


def _first_error(rejected: List[dict]) -> str:
    err = rejected[0].get("error") or {}
    detail = err.get("description") or err.get("message") if hasattr(err, "get") else None
    return f"first error: {detail}" if detail else "no error detail returned"


def refresh_dashboard_data(
    gis,
    mart_tables: Dict[str, List[dict]],
    layer_map: Dict[str, str],
    *,
    dry_run: bool = False,
) -> RefreshResult:
    """Truncate+append each hosted dashboard layer from the local data mart.

    One table's failure is recorded in ``failures`` and does not abort the
    rest. A table absent from ``layer_map`` is a WARNING + skip, not a crash.
    ``dry_run=True`` validates row keys against the hosted layer's fields and
    writes nothing.

    Per-feature rejections inside a non-raising ``edit_features()`` response
    are blocking failures, and the QA record names the resulting hosted state
    (EMPTY/PARTIAL) plus the re-run recovery path -- truncate-and-append has no
    transaction to roll back (issue #428).

    An empty ``mart_tables`` raises ``ValueError``: iterating zero tables and
    reporting ``tables_refreshed=0 failures=[]`` is indistinguishable from a
    successful refresh, so automation could not tell a no-op apart from a real
    run (issue #424).
    """
    if not mart_tables:
        raise ValueError(
            "no data-mart tables to refresh; refusing to report success for a "
            "refresh that validated and pushed nothing")
    result = RefreshResult()
    for table, rows in mart_tables.items():
        layer_id = layer_map.get(table)
        if not layer_id:
            result.qa.add(SEV_WARNING, "refresh_no_layer_mapping",
                          f"no hosted layer mapped for '{table}', skipping")
            continue
        truncated = False
        try:
            item = gis.content.get(layer_id)
            # Dash_* rows are non-spatial (no SHAPE column -- see
            # dashboard_data_mart.py's InsertCursor with no geometry), so a
            # hosted item for one is exposed under `.tables`, not `.layers`,
            # in the arcgis API. Resolve whichever is populated.
            subs = list(item.layers or []) + list(item.tables or [])
            layer = subs[0]

            if dry_run:
                known = _field_names(layer)
                unknown = {k for row in rows for k in row.keys()} - known
                if unknown:
                    result.qa.add(SEV_ERROR, "refresh_dry_run_schema_mismatch",
                                  f"'{table}' rows reference fields not on the "
                                  f"hosted layer: {sorted(unknown)}")
                    result.failures.append(table)
                    continue
                result.qa.add(SEV_INFO, "refresh_dry_run_ok",
                              f"'{table}' rows validated against hosted layer schema")
            else:
                layer.manager.truncate()
                truncated = True
                rejected = []
                if rows:
                    rejected = _rejected_adds(layer.edit_features(
                        adds=[{"attributes": row} for row in rows]))
                if rejected:
                    result.failures.append(table)
                    result.qa.add(SEV_ERROR, "refresh_table_partial",
                                  f"'{table}' was truncated and the service "
                                  f"rejected {len(rejected)} of {len(rows)} "
                                  f"row(s) ({_first_error(rejected)}); the "
                                  f"hosted table is now PARTIAL. "
                                  f"{_RECOVERY}")
                    continue
                result.qa.add(SEV_INFO, "refresh_table_pushed",
                              f"pushed {len(rows)} row(s) to '{table}'")

            result.rows_pushed[table] = len(rows)
            result.tables_refreshed += 1
        except Exception as exc:
            result.failures.append(table)
            state = (f"the hosted table is now EMPTY or PARTIAL. {_RECOVERY}"
                     if truncated else "the hosted table was not modified")
            result.qa.add(SEV_ERROR, "refresh_table_failed",
                          f"refresh failed for '{table}': {exc}; {state}")
    return result
