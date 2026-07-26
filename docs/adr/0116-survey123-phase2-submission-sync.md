# ADR-0116: Survey123 Phase 2 — incremental submission sync + canonical envelope (slice 1)

**Status:** Proposed (owner sign-off pending; live non-production gate legs
owner-gated)

**Date:** 2026-07-25

## Context

The Survey123 add-on roadmap (ADR-0112) Phase 2 adds the track's first live,
read-only command: pull new and changed submissions from a hosted survey by
stable identity and edit timestamp, and define the **canonical submission
envelope** that ADR-0113 relocated here from Phase 0 so it would be designed
against its first real consumer. The user directed the Phase 2 start on
2026-07-25 ("pickup phase 2 of survey123") — the explicit phase-start decision
ADR-0112 requires. Phase 1 (PR #364, ADR-0115) is unmerged but shares no code
with this slice, so this branch starts from `main`, not stacked.

Existing seams this slice extends rather than duplicates: the lazy
`runtime.sessions.agol_from_profile` provider, the harvester's incremental
epoch-ms `EditDate` convention and editor-tracking requirement,
`core/agol/sync_layer.py`'s pure-plan/lazy-fetch split, and
`normalize_survey123` + `route-survey123` as the downstream normalizer/GDB
path.

## Decision

- **One module owns Phase 2:** `core/envmon/survey_sync.py` — arcgis-free at
  import; `fetch_item_pulls()` is the single live seam (`# pragma: no cover`,
  fakes in tests), matching the sync_layer pattern.
- **Canonical envelope** (`SubmissionEnvelope`): item/layer identity,
  GlobalID, operation (`add`/`update`/`delete`), edit time (epoch ms),
  `repeat_path` (`""` for the parent layer, the repeat table's name
  otherwise) + `parent_global_id`, raw attributes, geometry, attachment
  metadata (id/name/size/content-type — downloads stay with the harvester),
  a canonical-JSON sha256 `payload_hash` (`""` for deletes), and pull
  provenance (`profile`, `pulled_at_ms`, `mode`, effective `since_ms`).
- **Sync semantics:** per-layer watermark = max `EditDate` seen; fetch uses a
  strictly-greater where-clause, so a repeated clean run pulls nothing and
  creates no duplicates. Editor tracking is required (same rule as the
  harvester's incremental mode). `add` vs `update` is classified by
  `CreationDate` against the watermark; first pull is all `add`s.
- **Deletions by GlobalID sweep:** each run queries the full current
  GlobalID set and diffs it against the checkpoint's known-ID set.
  `ponytail:` a row added *and* deleted entirely between runs is never
  observed, and a layer removed from the service drops its checkpoint state
  without emitting deletes for its known IDs — the envelope stream is a
  change feed, not an audit log; upgrade path is the feature-service
  `extractChanges` API if either gap ever matters.
- **Checkpoint after durable output:** `.survey123_sync_state.json` in the
  staging directory is written (atomically, tmp + `os.replace`) only after
  the staging artifacts are on disk. An interrupted run re-pulls the same
  window; downstream `append_records_idempotent` keeps re-imports
  duplicate-free.
- **Bounded replay + dry run:** `--since` re-pulls a window and never
  advances the checkpoint (and never regresses a stored watermark);
  `--dry-run` fetches, summarizes, writes nothing.
- **Staging artifacts feed the existing normalizer:** `envelopes_<ts>.jsonl`
  (the envelope stream) plus `submissions_<ts>.csv` — parent-layer
  add/update attributes only, the exact shape
  `route-survey123 --format csv` / `load_survey123_csv_submissions`
  consumes. Date fields (esriFieldTypeDate) render date-only at midnight UTC,
  else full timestamp — a real time-of-day then fails the normalizer's date
  parse *visibly* rather than this writer guessing a timezone and silently
  shifting a sampling date. GDB writes remain the explicit downstream LOCAL
  operation (`route-survey123`); this command is CLOUD and read-only.
- **Install contract (ADR-0112):** new `survey123` extra (same arcgis stack +
  distutils caveat as `cloud`, which stays supported). The command is always
  visible; without the extra it fails before any network work via
  `importlib.util.find_spec("arcgis")` with the exact
  `pip install "autogis[survey123]"` hint.
- **No new arcpy calls** (ADR-0077 n/a); the arcgis API usage reuses
  already-shipped patterns (`layer.query`, `attachments.get_list(oid=...)`,
  `editFieldsInfo`, `globalIdField` — the harvester's and sync_layer's exact
  calls).

## Consequences

- Exit-gate legs verifiable headlessly are met and pinned by tests
  (21 in `tests/envmon/test_survey_sync.py`): interrupted-run resume without
  checkpoint advance, repeat-run no-duplicates, edit/delete visibility,
  attachment metadata by stable identity, repeat-table envelopes, replay
  boundedness, dry-run writing nothing, staging CSV feeding the existing
  normalizer, the pre-network install hint, and (review round 1) the
  checkpoint↔`--item-id` mismatch guard — a foreign checkpoint would
  silently apply another survey's watermarks and fabricate deletes from its
  known-ID set. Suite 2623 green.
- **Owner-gated live legs remain open** (shared gate item 5 + "counts match a
  non-production hosted survey"): a live pull against a non-production
  hosted survey with representative new/edited/deleted/repeat/attachment
  submissions. Same pattern as Phases 7-9's owner-gated legs.
- Milestone B ("trusted field-data intake") is not claimed: Phase 3
  reconciliation has not started.
- Phase 5 (webhooks) now has the envelope it depends on, per ADR-0113's
  repointing.
- Rollback = revert the commit; the checkpoint file is additive staging
  state — deleting it simply makes the next run a full re-pull, which
  downstream idempotent import absorbs.

## Related

- ADR-0112 (add-on roadmap + install contract), ADR-0113 (envelope
  relocation to Phase 2), ADR-0115 (Phase 1, independent branch), ADR-0040
  (function-scope live seams), ADR-0044 (attribute-sync scope of Tool 6.2,
  unchanged)
- `docs/survey123-add-on-roadmap.md` Phase 2
- `docs/adr/logs/2026-07-25-agent-decisions.md` (branching and API-choice
  judgment calls)
