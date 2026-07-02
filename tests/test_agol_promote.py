"""Tests for Tool 6.10 -- PromoteAGOLDataBetweenStages (autogis.core.agol.promote).

Fake injected `gis` throughout (unittest.mock.MagicMock), mirroring
tests/test_agol_publish.py. `fetch_layer_schema` (the arcgis-touching seam
reused from audit_schema.py) is patched at the point of use in `promote.py`
so these tests never need to construct a real arcgis object.
"""
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from autogis.core.agol.promote import (
    STAGES,
    PromotionResult,
    plan_promotion,
    requires_approval,
    promote_layer,
)
from autogis.core.common.run_history import RunHistory


# -- a coded-value domain on both sides -- the case that actually proves
# _as_spec() converts fetched-schema domains correctly (see module docstring
# in promote.py). A domain-free schema would pass diff_schema() either way
# and would not catch a broken/missing conversion.
_FIELDS = [
    {
        "name": "WellType",
        "type": "esriFieldTypeString",
        "nullable": True,
        "domain": {
            "name": "WellTypeDomain",
            "codedValues": [{"code": "MW", "name": "Monitoring Well"}],
        },
    },
]
_MATCHING_SCHEMA = {"fields": _FIELDS}
_DRIFTED_SCHEMA = {"fields": [{"name": "OtherField", "type": "esriFieldTypeInteger",
                               "nullable": True, "domain": None}]}

_STAGE_MAP = {"wells": {"dev": "dev-item", "qa": "qa-item", "prod": "prod-item"}}


def _patched_fetch(schemas_by_item_id):
    """Return a stand-in for fetch_layer_schema keyed by item_id."""
    def _fetch(gis, *, item_id=None, layer_url=None, layer_index=0):
        return schemas_by_item_id[item_id]
    return _fetch


# ------------------------------------------------------------------ plan_promotion

def test_plan_promotion_allows_dev_to_qa():
    assert plan_promotion("dev", "qa") is True


def test_plan_promotion_allows_qa_to_prod():
    assert plan_promotion("qa", "prod") is True


def test_plan_promotion_raises_on_skip():
    with pytest.raises(ValueError):
        plan_promotion("dev", "prod")


@pytest.mark.parametrize("from_stage,to_stage", [
    ("qa", "dev"), ("prod", "qa"), ("prod", "dev"),
])
def test_plan_promotion_raises_on_backward(from_stage, to_stage):
    with pytest.raises(ValueError):
        plan_promotion(from_stage, to_stage)


def test_plan_promotion_raises_on_unknown_stage():
    with pytest.raises(ValueError):
        plan_promotion("dev", "staging")


# ------------------------------------------------------------------ requires_approval

def test_requires_approval_qa_to_prod():
    assert requires_approval("qa", "prod") is True


def test_requires_approval_dev_to_qa_false():
    assert requires_approval("dev", "qa") is False


# ------------------------------------------------------------------ promote_layer

def test_promote_blocked_schema_does_not_copy():
    gis = MagicMock()
    fetch = _patched_fetch({"dev-item": _MATCHING_SCHEMA, "qa-item": _DRIFTED_SCHEMA})
    with patch("autogis.core.agol.promote.fetch_layer_schema", side_effect=fetch):
        result = promote_layer(
            gis, layer="wells", stage_map=_STAGE_MAP,
            from_stage="dev", to_stage="qa",
        )
    assert result.status == "blocked-schema"
    assert result.rows_copied == 0
    gis.content.get.assert_not_called()  # no data-copy step reached


def test_promote_blocked_approval_does_not_copy():
    gis = MagicMock()
    fetch = _patched_fetch({"qa-item": _MATCHING_SCHEMA, "prod-item": _MATCHING_SCHEMA})
    with patch("autogis.core.agol.promote.fetch_layer_schema", side_effect=fetch):
        result = promote_layer(
            gis, layer="wells", stage_map=_STAGE_MAP,
            from_stage="qa", to_stage="prod", approved_by=None,
        )
    assert result.status == "blocked-approval"
    assert result.rows_copied == 0
    gis.content.get.assert_not_called()


def test_promote_dev_to_qa_succeeds_without_approval():
    gis = MagicMock()
    src_layer, dst_layer = MagicMock(), MagicMock()
    src_layer.query.return_value.features = ["f1", "f2"]
    gis.content.get.side_effect = lambda iid: {
        "dev-item": MagicMock(layers=[src_layer]),
        "qa-item": MagicMock(layers=[dst_layer]),
    }[iid]
    fetch = _patched_fetch({"dev-item": _MATCHING_SCHEMA, "qa-item": _MATCHING_SCHEMA})

    with patch("autogis.core.agol.promote.fetch_layer_schema", side_effect=fetch):
        result = promote_layer(
            gis, layer="wells", stage_map=_STAGE_MAP,
            from_stage="dev", to_stage="qa",
        )

    assert result.status == "promoted"
    assert result.rows_copied == 2
    dst_layer.manager.truncate.assert_called_once()
    dst_layer.edit_features.assert_called_once_with(adds=["f1", "f2"])


def test_promote_qa_to_prod_with_approval_writes_run_history(tmp_path):
    gis = MagicMock()
    src_layer, dst_layer = MagicMock(), MagicMock()
    src_layer.query.return_value.features = ["f1", "f2", "f3"]
    gis.content.get.side_effect = lambda iid: {
        "qa-item": MagicMock(layers=[src_layer]),
        "prod-item": MagicMock(layers=[dst_layer]),
    }[iid]
    fetch = _patched_fetch({"qa-item": _MATCHING_SCHEMA, "prod-item": _MATCHING_SCHEMA})
    rh_path = tmp_path / "run_history.csv"
    run_history = RunHistory(rh_path)

    with patch("autogis.core.agol.promote.fetch_layer_schema", side_effect=fetch):
        result = promote_layer(
            gis, layer="wells", stage_map=_STAGE_MAP,
            from_stage="qa", to_stage="prod", approved_by="PM Name",
            run_history=run_history,
        )

    assert result.status == "promoted"
    assert result.rows_copied == 3
    assert result.approved_by == "PM Name"

    records = run_history.query(tool_name="agol-promote", site_id="wells")
    assert len(records) == 1
    rec = records[0]
    assert rec.status == "success"
    inputs = json.loads(rec.inputs) if isinstance(rec.inputs, str) else rec.inputs
    assert inputs["approved_by"] == "PM Name"
    assert inputs["from_stage"] == "qa"
    assert inputs["to_stage"] == "prod"
    outputs = json.loads(rec.outputs) if isinstance(rec.outputs, str) else rec.outputs
    assert outputs["rows_copied"] == 3
    assert outputs["promotion_status"] == "promoted"


def test_promote_blocked_approval_writes_run_history(tmp_path):
    gis = MagicMock()
    fetch = _patched_fetch({"qa-item": _MATCHING_SCHEMA, "prod-item": _MATCHING_SCHEMA})
    rh_path = tmp_path / "run_history.csv"
    run_history = RunHistory(rh_path)

    with patch("autogis.core.agol.promote.fetch_layer_schema", side_effect=fetch):
        result = promote_layer(
            gis, layer="wells", stage_map=_STAGE_MAP,
            from_stage="qa", to_stage="prod", run_history=run_history,
        )

    assert result.status == "blocked-approval"
    records = run_history.query(tool_name="agol-promote", site_id="wells")
    assert len(records) == 1
    assert records[0].status == "warning"


def test_promote_missing_stage_map_entry_raises():
    gis = MagicMock()
    with pytest.raises(KeyError):
        promote_layer(gis, layer="unknown-layer", stage_map=_STAGE_MAP,
                      from_stage="dev", to_stage="qa")


def test_promote_copy_failure_after_truncate_writes_error_run_history(tmp_path):
    # Target is truncated, then edit_features() raises -- the promotion must
    # not crash uncrated: it should record an error status (surfacing the
    # partial-truncate state) and return a result instead of propagating.
    gis = MagicMock()
    src_layer, dst_layer = MagicMock(), MagicMock()
    src_layer.query.return_value.features = ["f1", "f2"]
    dst_layer.edit_features.side_effect = RuntimeError("AGOL 500")
    gis.content.get.side_effect = lambda iid: {
        "dev-item": MagicMock(layers=[src_layer]),
        "qa-item": MagicMock(layers=[dst_layer]),
    }[iid]
    fetch = _patched_fetch({"dev-item": _MATCHING_SCHEMA, "qa-item": _MATCHING_SCHEMA})
    rh_path = tmp_path / "run_history.csv"
    run_history = RunHistory(rh_path)

    with patch("autogis.core.agol.promote.fetch_layer_schema", side_effect=fetch):
        result = promote_layer(
            gis, layer="wells", stage_map=_STAGE_MAP,
            from_stage="dev", to_stage="qa", run_history=run_history,
        )

    dst_layer.manager.truncate.assert_called_once()
    assert result.status == "copy-failed"
    assert result.rows_copied == 0
    assert any(r.category == "promotion_copy_failed" for r in result.qa.records)

    records = run_history.query(tool_name="agol-promote", site_id="wells")
    assert len(records) == 1
    assert records[0].status == "error"
    outputs = json.loads(records[0].outputs) if isinstance(records[0].outputs, str) else records[0].outputs
    assert outputs["promotion_status"] == "copy-failed"
