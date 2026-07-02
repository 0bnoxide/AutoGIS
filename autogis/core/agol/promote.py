"""PromoteAGOLDataBetweenStages -- DEV->QA->PROD release discipline for AGOL (Tool 6.10).

Stage-promotion driver on the injected-``gis`` / lazy-``arcgis`` contract (same
seam as ``publish.py``). A promotion only copies data when:

  (a) the schema of the source and target stage items match (reuses
      ``diff_schema`` / ``fetch_layer_schema`` from ``audit_schema.py`` --
      Tool 6.6 -- no schema comparison is reimplemented here), and
  (b) an approver is recorded for qa->prod (dev->qa needs none).

Every promotion attempt -- blocked or successful -- writes a record via the
existing ``RunHistory`` (ADR-0017); there is no separate/parallel audit log.

No ``arcgis`` import at module load time: ``fetch_layer_schema`` (reused from
``audit_schema``) lazy-imports ``arcgis.features.FeatureLayer`` only when
actually called, and the data-copy step here only calls methods on the
injected ``gis`` object -- it never imports an arcgis class itself.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from ..common.qa import QACollector, SEV_INFO, SEV_ERROR
from ..common.run_history import RunHistory, RunRecord
from .audit_schema import diff_schema, fetch_layer_schema

STAGES = ("dev", "qa", "prod")
_ORDER = {stage: i for i, stage in enumerate(STAGES)}

# ponytail: promotion-status -> RunRecord.status mapping. RunRecord status is
# a generic pipeline enum ("success"|"warning"|"error"|"cancelled") that
# predates this tool, so a schema-drift block (a real data problem) maps to
# "error" and an approval-pending block (a procedural gate, nothing broken)
# maps to "warning". Widen RunRecord itself only if a consumer later needs a
# dedicated promotion-status column -- the raw status also travels in
# `outputs` below so no information is lost.
_RUN_HISTORY_STATUS = {
    "promoted": "success",
    "blocked-schema": "error",
    "blocked-approval": "warning",
    "copy-failed": "error",
}


@dataclass
class PromotionResult:
    layer: str
    from_stage: str
    to_stage: str
    rows_copied: int
    approved_by: Optional[str]
    status: str            # "promoted" | "blocked-schema" | "blocked-approval" | "copy-failed"
    qa: QACollector


def plan_promotion(from_stage: str, to_stage: str) -> bool:
    """Return True if from_stage -> to_stage is an allowed single-step promotion.

    Raises ValueError on unknown stages, same-stage, backward, or skip moves
    (e.g. dev->prod, qa->dev, prod->qa).
    """
    if from_stage not in STAGES or to_stage not in STAGES:
        raise ValueError(f"unknown stage(s): {from_stage!r} -> {to_stage!r}")
    if _ORDER[to_stage] - _ORDER[from_stage] != 1:
        raise ValueError(
            f"invalid promotion {from_stage!r} -> {to_stage!r}: only single-step "
            "forward moves are allowed (dev->qa, qa->prod)"
        )
    return True


def requires_approval(from_stage: str, to_stage: str) -> bool:
    """qa->prod requires a recorded approver; dev->qa (and any other move) does not."""
    return (from_stage, to_stage) == ("qa", "prod")


def _as_spec(fetched_schema: dict, layer_name: str) -> dict:
    """Reshape a *fetched* AGOL schema dict into local-spec shape.

    ``diff_schema(fetched_schema, local_spec)`` expects the two sides in
    different domain-key casings (AGOL fetched: "codedValues", local spec:
    "coded_values" -- see audit_schema.py's module docstring). For a
    stage-to-stage comparison both sides are actually *fetched* AGOL schemas,
    so without this rename every coded-value domain looks like 100% drift
    (populated "codedValues" vs. an always-empty "coded_values" read) even
    when source and target are identical. Field-level type/nullable keys are
    already spelled the same in both formats and need no conversion.
    """
    fields = []
    for f in fetched_schema.get("fields", []):
        f = dict(f)
        domain = f.get("domain")
        if isinstance(domain, dict) and "codedValues" in domain:
            domain = dict(domain)
            domain["coded_values"] = domain.pop("codedValues")
        f["domain"] = domain
        fields.append(f)
    return {"layer_name": layer_name, "fields": fields}


def _copy_layer_data(gis, src_item_id: str, dst_item_id: str, layer_index: int = 0) -> int:
    """Copy all features from the source stage item layer to the target stage item layer.

    Truncates the target layer, then re-adds every source feature. Uses only
    methods on the injected ``gis`` (and the Item/FeatureLayer objects it
    returns) -- no arcgis class is constructed here.
    """
    src_layer = gis.content.get(src_item_id).layers[layer_index]
    dst_layer = gis.content.get(dst_item_id).layers[layer_index]
    features = src_layer.query(where="1=1", out_fields="*").features
    dst_layer.manager.truncate()
    if features:
        dst_layer.edit_features(adds=features)
    return len(features)


def _log_promotion(run_history: Optional[RunHistory], result: PromotionResult,
                    started_at: datetime) -> None:
    if run_history is None:
        return
    counts = result.qa.counts_by_severity()
    run_history.write(RunRecord(
        run_id=str(uuid.uuid4()),
        tool_name="agol-promote",
        site_id=result.layer,
        event_id=None,
        started_at=started_at,
        finished_at=datetime.now(),
        status=_RUN_HISTORY_STATUS[result.status],
        inputs={
            "from_stage": result.from_stage,
            "to_stage": result.to_stage,
            "approved_by": result.approved_by,
        },
        outputs={
            "rows_copied": result.rows_copied,
            "promotion_status": result.status,
        },
        qa_count_error=counts.get(SEV_ERROR, 0),
        qa_count_warning=counts.get("WARNING", 0),
        qa_count_info=counts.get(SEV_INFO, 0),
        message=result.qa.records[-1].message if result.qa.records else "",
    ))


def promote_layer(
    gis,
    *,
    layer: str,
    stage_map: Dict[str, Dict[str, str]],
    from_stage: str,
    to_stage: str,
    approved_by: Optional[str] = None,
    run_history: Optional[RunHistory] = None,
) -> PromotionResult:
    """Validate schema + approval, copy data, and log the promotion attempt.

    ``stage_map`` maps layer name -> {"dev"/"qa"/"prod": item_id}. Raises
    ValueError (via plan_promotion) for an invalid stage transition, and
    KeyError if stage_map has no item id for the requested layer/stages --
    both are caller/config errors, not a blocked-promotion *outcome*, so
    neither writes a run-history record. ``run_history`` is optional
    (best-effort logging, matching the optional-QACollector pattern in
    publish.py) but should be supplied in production -- every real promotion
    is meant to be logged.
    """
    plan_promotion(from_stage, to_stage)
    started_at = datetime.now()
    qa = QACollector()

    items = stage_map.get(layer, {})
    src_id, dst_id = items.get(from_stage), items.get(to_stage)
    if not src_id or not dst_id:
        raise KeyError(
            f"stage_map has no item id for layer={layer!r}, stages "
            f"{from_stage!r}/{to_stage!r}"
        )

    src_schema = fetch_layer_schema(gis, item_id=src_id)
    dst_schema = fetch_layer_schema(gis, item_id=dst_id)
    report = diff_schema(dst_schema, _as_spec(src_schema, layer))
    if report.has_drift:
        qa.add(SEV_ERROR, "promotion_blocked_schema",
               f"{layer}: schema drift between {from_stage!r} and {to_stage!r} "
               f"({len(report.drift_items)} item(s)) -- promotion blocked")
        result = PromotionResult(layer, from_stage, to_stage, 0, approved_by,
                                  "blocked-schema", qa)
        _log_promotion(run_history, result, started_at)
        return result

    if requires_approval(from_stage, to_stage) and not approved_by:
        qa.add(SEV_ERROR, "promotion_blocked_approval",
               f"{layer}: {from_stage!r} -> {to_stage!r} requires an approver "
               "and none was recorded")
        result = PromotionResult(layer, from_stage, to_stage, 0, None,
                                  "blocked-approval", qa)
        _log_promotion(run_history, result, started_at)
        return result

    try:
        rows_copied = _copy_layer_data(gis, src_id, dst_id)
    except Exception as exc:
        qa.add(SEV_ERROR, "promotion_copy_failed",
               f"{layer}: data copy {from_stage!r} -> {to_stage!r} failed after "
               f"the target layer was truncated -- {to_stage!r} may now be "
               f"partially or fully empty until this promotion is retried: {exc}")
        result = PromotionResult(layer, from_stage, to_stage, 0, approved_by,
                                  "copy-failed", qa)
        _log_promotion(run_history, result, started_at)
        return result

    qa.add(SEV_INFO, "promotion_succeeded",
           f"{layer}: promoted {rows_copied} row(s) {from_stage!r} -> {to_stage!r}")
    result = PromotionResult(layer, from_stage, to_stage, rows_copied, approved_by,
                              "promoted", qa)
    _log_promotion(run_history, result, started_at)
    return result
