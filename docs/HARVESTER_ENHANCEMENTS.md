# Harvester enhancements — before/after-merge evaluation

**Question:** four proposed harvester features — implement before or after the
suite merge (see `MERGE_PLAN.md`)?

**Verdict:** implement all four **after** the merge, but fold three design
requirements **into** the merge now so the post-merge work is a drop-in, not a
second refactor. Rationale below is grounded in the current harvester code.

## Why "after" — the shared reason

Every one of these features touches a substrate the merge intentionally
rewrites:

- **Config** — `core/models.HarvestConfig` (flat) → typed dataclass with JSON
  fallback (MERGE_PLAN §3.1). Any new config knob (worker count, rate limit,
  hash algorithm) built now gets re-expressed at merge.
- **Reporting / manifest** — `RunSummary` + `Manifest` (CSV/JSON from the
  `AttachmentResult` dataclass) → `QACollector` + unified writers
  (MERGE_PLAN §3.2). Three of the four features add manifest
  columns or output formats — i.e. they ARE changes to this substrate.
- **Skip / idempotency** — harvester's `skip_existing` (currently
  `os.path.exists`) and `state.py` watermark overlap conceptually with envmon's
  idempotent unique-key imports. Checksums/dedup belong in a single
  "seen-before" concept, not two.

Building the surfaces of these features before the merge means building on
`HarvestConfig`/`RunSummary`/`Manifest`, then porting them in MERGE_PLAN steps
1–2 when those are replaced. Net: double work + reconciliation risk — the exact
API-drift failure mode flagged in the env project history.

## Three requirements to bake into the merge design (do now)

So that "after" is cheap, the merge's `core/common` must be built with these in
mind even though the features land later:

1. **Thread-safe reporter + progress/cancel hook.** The reporter introduced in
   MERGE_PLAN step 2 must be safe to call from worker threads and expose a
   cancel check. This makes parallel downloads a drop-in.
2. **Manifest schema reserves provenance fields.** The unified manifest/result
   record should reserve columns for `checksum` (+ algorithm), `geometry`
   (WKT/GeoJSON), and `source_table` / `relationship_id`. Adding these later
   without a reserved schema means a second manifest migration.
3. **One "seen-before" abstraction.** Model checksum-based skip (harvester) and
   unique-key idempotent skip (envmon import) as one concept in `core/common`,
   not two parallel implementations.

All four features are **HYBRID / cloud-OK** (pure `arcgis` API + stdlib hashing;
no arcpy). They stay in shared harvester core and are not runtime-gated.

## Per-feature assessment

### 1. Parallel downloads + configurable rate-limiting
- **Touches:** `harvester.harvest` loop (sequential today), config (new
  `max_workers`, `rate_limit`), reporter (`RunSummary.record` /
  `Manifest.add` are **not thread-safe** today). `download.py` is already
  per-attachment and thread-friendly as-is.
- **Merge coupling:** the download *orchestration* is merge-neutral; the
  config knobs and thread-safe reporting are not. Built on today's
  `RunSummary` it would be reworked at merge step 2.
- **Effort/risk:** moderate; error isolation is already per-attachment. Use a
  thread pool (downloads are I/O-bound) + a token-bucket rate limiter.
- **Sequence:** first feature after merge (highest value, self-contained once
  the reporter is thread-safe).

### 2. Metadata manifest (CSV / GeoJSON)
- **Touches:** `manifest.py` (new format + richer fields), `AttachmentResult`
  (add metadata columns), and **`harvester.harvest` currently queries with
  `return_geometry=False`** — GeoJSON requires flipping that and threading
  geometry through to the manifest.
- **Merge coupling:** **highest.** This feature is a change to the manifest
  substrate itself, which the merge reconciles with envmon's QACollector
  writers (CSV/JSON/MD already exist there — likely reuse).
- **Effort/risk:** low-moderate once the unified writer exists; wasteful before.
- **Sequence:** after merge, on the unified writer. Cheap then.

### 3. Deduplication & checksums (MD5 / SHA)
- **Touches:** `download.py` (hash bytes on download — fully independent,
  low-risk primitive), `AttachmentResult`/manifest (+hash column —
  merge-coupled), `harvester` skip logic (checksum skip upgrades the
  `os.path.exists` check), possibly `state.py` (cross-run seen-hashes).
- **Merge coupling:** the hashing primitive is merge-neutral and the easiest
  thing to pull forward if you want an early win; the dedup *policy* + manifest
  column + skip semantics are merge-coupled (req. 2 and 3 above).
- **Effort/risk:** low for hashing; moderate for cross-run dedup policy.
- **Sequence:** after merge with the rest; if impatient, the `download.py`
  hashing primitive can land early without touching config/manifest.

### 4. Related-tables attachment support
- **Touches:** `harvester.resolve_layer` + the iteration model. Today it is a
  single `layer.query → features → attachments.get_list`. Related tables
  require querying relationship classes (`query_related_records` / item
  relationships), walking related rows, and fetching *their* attachments — plus
  recording `source_table`/`relationship_id` provenance in the manifest.
- **Merge coupling:** iteration logic is merge-neutral; the provenance fields
  it needs are merge-coupled (req. 2). Logically independent of envmon, so
  "before" is *possible* — just not advisable given the schema dependency.
- **Effort/risk:** **largest of the four**; deserves its own design + tests
  (mock related-record queries the way the layer is injected today).
- **Sequence:** last; build on the final config/manifest substrate.

## Recommended order (all post-merge)

1. Parallel downloads + rate limit (high value, self-contained on a thread-safe
   reporter).
2. Checksums/dedup (builds on the manifest schema + skip model).
3. GeoJSON/metadata manifest (small once the unified writer and geometry plumbing
   exist).
4. Related-tables (largest; own design pass).

## One-line summary for the merge

No change to the merge scope — but when Claude Code builds `core/common` in
MERGE_PLAN steps 1–2, the reporter must be **thread-safe with a cancel hook** and
the manifest record must **reserve `checksum`, `geometry`, and
`source_table`/`relationship_id`** fields. That is the entire cost of deferring
these four features, and it is far cheaper than building them twice.
