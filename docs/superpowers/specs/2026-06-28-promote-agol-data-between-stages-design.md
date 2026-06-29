# PromoteAGOLDataBetweenStages Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** PromoteAGOLDataBetweenStages (Tool 6.10)
**Priority:** MEDIUM — brings release discipline (DEV→QA→PROD) to AGOL content
**Runtime:** CLI ✓ / AGOL ✓ — `arcgis` (cloud extra), never arcpy

---

## Problem

AGOL content has no release stages: data published for review can be the same item a
client dashboard reads, so unvalidated data can reach stakeholders. There is no
DEV→QA→PROD promotion with a validation+approval gate, and no record of who promoted what.

---

## Approach

**Chosen:** A stage-promotion driver on the injected-`gis` / lazy-`arcgis` contract, with
the promotion gate logged via `WriteRunHistory` (10.5) extended with promotion/approval
state (per the roadmap's "extends RunHistory"). A stage map (YAML) names the DEV/QA/PROD
item ids per logical layer. Promotion copies data DEV→QA→PROD only when (a) the schema of
source and target match (reuses `AuditAGOLSchemaAgainstLocalConfig` logic, 6.6, planned)
and (b) an `--approve` flag (or recorded approver) is present for QA→PROD. Every promotion
writes a run-history record (from, to, item, approver, status).

The **stage-transition rules** (which transitions need approval, validation ordering) are
pure and tested without AGOL; only the data copy touches `arcgis`.

**Rejected: silent overwrite of PROD.** PROD writes require an explicit approver; the gate
is the entire reason the tool exists.

**Rejected: a new audit log.** Promotion state extends the existing run-history record
(ADR-0017), not a parallel log.

**Rejected: `GIS()` in core.** Injected; tests use a fake gis.

---

## Architecture

```
autogis/
  core/common/
    run_history.py            ← EXISTS (extended with promotion/approval fields)
  core/agol/
    promote.py                ← NEW (injected gis, lazy arcgis)
  adapters/
    cli.py                    ← add `agol promote` command
tests/
  test_agol_promote.py        ← NEW (fake gis)
```

---

## Public API (`promote.py`)

```python
STAGES = ("dev", "qa", "prod")

@dataclass
class PromotionResult:
    layer: str
    from_stage: str
    to_stage: str
    rows_copied: int
    approved_by: str | None
    status: str                 # promoted | blocked-schema | blocked-approval
    qa: QACollector

def plan_promotion(from_stage: str, to_stage: str) -> bool:
    """Return True if the transition is allowed; raise on skip/backward moves."""

def requires_approval(from_stage: str, to_stage: str) -> bool:
    """qa->prod requires approval; dev->qa does not."""

def promote_layer(
    gis,                        # injected GIS
    *,
    layer: str,
    stage_map: dict[str, dict[str, str]],   # layer -> {dev,qa,prod: item_id}
    from_stage: str,
    to_stage: str,
    approved_by: str | None = None,
) -> PromotionResult:
    """Validate schema + approval, copy data, write a run-history promotion record."""
```

---

## CLI Command

```
autogis agol promote \
  --profile <agol_profile.yaml> \
  --stage-map <stages.yaml> \
  --layer wells \
  --from qa --to prod \
  --approve --approved-by "PM Name" \
  [--report <promote_qa.md>]
```

---

## Test Strategy

`tests/test_agol_promote.py` — fake injected `gis`:

1. `plan_promotion("dev","qa")` allowed; `plan_promotion("prod","dev")` raises.
2. `requires_approval("qa","prod")` True; `("dev","qa")` False.
3. `promote_layer` qa→prod without approver → `status="blocked-approval"`, no copy.
4. Schema mismatch source/target → `status="blocked-schema"`, no copy.
5. Approved qa→prod → data copied, run-history record written with approver.
6. `promote.py` imports without `arcgis` installed.
