# Parallel-Agent Dispatch — Pre-Merge Recon Wave

**Status:** design / approved, not yet executed
**Date:** 2026-06-19
**Scope:** MERGE_PLAN steps 1–6 (envmon suite merge) only. Harvester
enhancements and a reusable dispatch methodology are explicitly out of scope.
**Companions:** `docs/MERGE_PLAN.md`, `docs/HARVESTER_ENHANCEMENTS.md`,
`docs/CLAUDE_CODE_KICKOFF.md`

---

## 1. Problem & key finding

The merge is a **sequential spine**: MERGE_PLAN steps 1→2→3→4→5→6 each build on
the prior commit and the plan mandates one reviewable commit per step. Naive
"fan out all the tasks to parallel agents" is therefore wrong — it manufactures
parallelism the dependency graph does not allow.

Decisions taken during brainstorming:

- **Step 4** (repackage 23 envmon modules + port 56 tests) is **single-agent,
  linear.** The relative-import rewrite touches every file and the modules
  import each other; parallel builders would race on a shared import graph and
  break the single-commit rule. Not parallelized.
- **Step 5** (9 Tool classes + CLI subcommands) lands in shared files
  (`toolbox.pyt`, `cli.py`) → also not a clean fan-out target.
- **The genuine parallel opportunity is read-only reconnaissance**, not
  building. Six independent audits verify MERGE_PLAN's ground-truth claims
  before the linear builder starts. They share no state, write nothing, and
  de-risk every downstream step. This is the only fan-out in scope.

This matches MERGE_PLAN's own warning: *"re-verify against the actual source
before editing — do not trust this summary over the code."* The recon wave is
that verification, done in parallel.

## 2. Architecture

- **Orchestrator** = the main session. Owns dispatch, consolidation,
  adjudication, and the build spine afterward.
- **Workers** = 6 read-only `Explore` / `general-purpose` agents, dispatched in
  a single message so they run in parallel. **No git worktrees** — the agents
  write nothing, so no isolation is needed.
- **Hard rule:** recon agents are read-only. Any write attempt is a brief
  violation → discard that agent's output and re-run it.

### Worker report format (fixed)

Every agent returns one or more records in this shape:

```
CLAIM:    <the MERGE_PLAN assertion being checked>
VERDICT:  confirmed | corrected | needs-human
EVIDENCE: <file:line references>
DELTA:    <what MERGE_PLAN gets wrong, if anything>
RISK:     <what breaks in the build if this is left unaddressed>
```

## 3. The six recon streams

Scoped to avoid overlap. Each verifies a specific MERGE_PLAN claim and feeds a
specific downstream step.

| # | Stream | Brief | Verifies | Feeds |
|---|---|---|---|---|
| R1 | arcpy-boundary audit | grep all 23 `staging/envmon-incoming/src/*.py` for `arcpy`; classify free vs edge vs lazy-inside-fn | "14 of 23 arcpy-free; rest lazy at edge"; "import succeeds w/o arcpy" | runtime guard, import-success rule (§2 MERGE_PLAN) |
| R2 | import-graph map | extract every `from <mod> import` / `import <mod>` across the 23 modules + the `.pyt`; output adjacency list + topological order | non-namespaced flat imports needing relative rewrite | step 4 relative-rewrite order |
| R3 | test inventory | catalog `tests/` (3 modules, conftest, synthetic workbook fixtures); tag each test arcpy-dependent vs pure | the "56 tests" count + which are CI-able | step 4 port + CI gate |
| R4 | config reconcile | enumerate `HarvestConfig` fields vs `SiteConfig`/`ParserProfile`/`FigureSpec.load()` + `ConfigError` | §3.1 config systems | unified `core/common/config.py` field set |
| R5 | reporting reconcile | map `RunSummary`+`Manifest` API vs `QACollector`/`QARecord`+`_ArcpyHandler`; pinpoint non-thread-safe calls; list provenance fields to reserve | §3.2 + HARVESTER_ENHANCEMENTS forward reqs | reporter design; reserved schema (checksum/geometry/source_table/relationship_id) |
| R6 | caveat audit | locate in code: H281 draft profile, untested arcpy paths, `average_parent_and_duplicate` WARNING, null screening-levels file | the 4 carried-over caveats (§1 MERGE_PLAN) | no-regress guard before/throughout build |

## 4. Consolidation

After all six return, the orchestrator merges reports into
`docs/superpowers/specs/2026-06-19-mergeplan-deltas.md`:

- A table: claim → verdict → delta.
- **Corrections to MERGE_PLAN** — the deltas that actually change build
  instructions.
- **needs-human queue** — anything an agent could not settle (e.g. H281
  profile verification against the real workbook, ambiguous lazy-import cases).
- **Import graph + topo order** (R2 output) as a dedicated block step 4
  consumes directly.

## 5. Sequencing vs the build spine

- The recon wave runs **once, before step 1**, and **blocks** the builder.
  Rationale: any delta can change scaffolding decisions (config dataclass shape,
  reporter API surface, runtime-guard placement). Cheaper to learn it before
  `core/common` exists than to refactor after.
- The build spine stays **single-threaded** 1→2→3→4→5→6, exactly as
  MERGE_PLAN §5 specifies. **No agents run alongside the builder** — that would
  reintroduce a shared-state race on the live `merge/envmon-suite` branch.
- This design covers only the recon wave + its hand-off. The step-1→6 build
  plan itself is produced afterward by the writing-plans skill.

## 6. Failure handling

- **Thin/empty agent result** → orchestrator re-briefs that one stream, not the
  whole wave.
- **Two agents contradict** → orchestrator reads the cited files, adjudicates,
  and records the resolution in the deltas doc.
- **needs-human items** → surfaced to the user before step 1. The builder does
  not proceed past an R6 caveat-regression risk that is unbacked.
- **Read-only violation** → discard + redo (see §2).

## 7. Done criteria

- Deltas doc committed.
- needs-human queue cleared or explicitly acknowledged by the user.
- Hand off to the writing-plans skill to produce the actual step-1→6
  implementation plan, now grounded in verified ground truth rather than the
  unverified MERGE_PLAN summary.
