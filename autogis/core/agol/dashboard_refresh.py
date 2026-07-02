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
    """
    result = RefreshResult()
    for table, rows in mart_tables.items():
        layer_id = layer_map.get(table)
        if not layer_id:
            result.qa.add(SEV_WARNING, "refresh_no_layer_mapping",
                          f"no hosted layer mapped for '{table}', skipping")
            continue
        try:
            layer = gis.content.get(layer_id).layers[0]

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
                if rows:
                    layer.edit_features(adds=[{"attributes": row} for row in rows])
                result.qa.add(SEV_INFO, "refresh_table_pushed",
                              f"pushed {len(rows)} row(s) to '{table}'")

            result.rows_pushed[table] = len(rows)
            result.tables_refreshed += 1
        except Exception as exc:
            result.failures.append(table)
            result.qa.add(SEV_ERROR, "refresh_table_failed",
                          f"refresh failed for '{table}': {exc}")
    return result
