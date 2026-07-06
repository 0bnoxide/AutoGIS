# Tool workflow wiring — declarative multi-tool recipes (brainstorm)

**Status:** brainstorm only — no decision, no code. **Date:** 2026-07-06.

This is options + open questions, in the same spirit as
[`2026-07-03-unified-gui-planning.md`](2026-07-03-unified-gui-planning.md)
(§2.4 named this exact gap "V2, not MVP" and deferred it). Nothing here is
decided; it exists so the next session/reviewer isn't starting from zero.

---

## 1. What already exists — don't re-propose this

- **`FullPipeline`** (`autogis/adapters/toolbox.pyt`, Tool 7): the one real
  multi-tool chain today. Hardcoded, linear, Pro-only: `run_import()` → QA
  gate (halts only on FAIL) → per-figure-spec loop of
  `build_current_event_wide()` → `generate_callout_features()` → optional
  `build_groundwater_contours()` → a deliberate stop **before** export so
  layouts can be reviewed. No config, no reordering, no reuse outside this
  one class.
- **The GUI executor stack** (ADR-0053/0055/0056, shipped 2026-07-04/05) is
  already a *generic* one level up from `FullPipeline`:
  `Step` (command + values + `fail_on`/`pause_on_warning`/checkpoint),
  `Workflow` (name + ordered `Step` tuple), `WorkflowRunner` (single-flight
  `advance`/`pause`/`resume`/`cancel`), `decide()` (exit code + injected
  `qa.csv` → HALT/PAUSE_FOR_REVIEW/CONTINUE), `build_step()` (form values →
  `Step`). This already generalizes `FullPipeline`'s halt-gate and
  stop-for-review patterns to *any* CLI command, not just the 4 hardcoded
  ones — that generalization is done.
- **What it does *not* do yet** (confirmed by reading `runner.py`/`forms.py`
  directly — `app.py` only ever builds single-step `Workflow`s so far):
  no persisted/named multi-step recipe, no data flowing from one step's
  result into the next step's args, no conditional/branching step selection.
- **`job_queue.py`** generates an ordered `JobEntry` list (tool × site,
  CLOUD→HYBRID→LOCAL sort) from a manifest, but nothing executes that list —
  it's a planning report, not a runner. It's the natural source of "what
  order should these tools run in" logic for recipe validation (§4).

**The actual gap**, matching what §2.4 scoped as V2: (a) a way to *define* a
named multi-tool recipe once and run it repeatedly, (b) data piping between
steps, (c) whether/how much branching is needed, (d) a GUI screen to build
recipes interactively. Below are options for each — no recommendation is
locked in beyond a lean, and every one needs the user's sign-off before any
code gets written (per CLAUDE.md's phase-gate norm for anything tool-batch
or architecture-adjacent).

---

## 2. Recipe definition format

**Option A — YAML file, same shape as existing config** (site configs,
parser profiles, figure specs already live in `autogis/config/`). A recipe
would be `{name, steps: [{command, args, output_bindings}, ...]}`.
Versionable, diffable, reviewable in a PR, and consistent with how every
other configurable thing in this codebase is expressed — no new pattern to
learn.

**Option B — Python-registry of hardcoded recipes** (a `RECIPES: dict[str,
Workflow]` module, `FullPipeline`-style but centralized). Simpler to
implement, zero new parsing code, but back to "editing a class to add a
recipe" — the exact rigidity this whole exercise is meant to fix.

**Option C — GUI-only, no persisted file** (build a workflow interactively
in the builder screen, run it once, discard). Lowest implementation cost,
but recipes can't be shared, versioned, or run headless/scheduled — a
poor fit for a suite whose other 105 tools are all CLI-first.

**Lean:** A, for consistency with the rest of the config surface — but B's
"simpler, no new parser" argument is real and worth weighing if the first
few recipes turn out to be few and stable (YAGNI cuts against inventing a
schema for 2 recipes).

## 3. Data flowing between steps

Real recipes need this — e.g. `import-rtk-survey`'s generated `--batch-id`
feeding a later `export-survey-cad` step, or `full-pipeline`'s GDB path
threading through every stage.

**Option A — explicit named outputs.** Each `Step` declares which of its
own args are also *outputs* other steps can reference (e.g. a template
`${steps.import_rtk.batch_id}` resolved before the next step runs). Explicit,
auditable, matches this codebase's preference for typed/structured records
over implicit state (`QACollector`, `RunRecord`, `SurveyPointRaw` — the
project already prefers named fields over grab-bag dicts everywhere else).

**Option B — shared mutable context dict**, steps read/write freely. Less
code, but implicit — a later step silently depending on an earlier one
writing a particular key is exactly the kind of hidden coupling this
codebase's ADRs have repeatedly steered away from (e.g. ADR-0053 rejecting
stdout-parsing in favor of structured `qa.csv` for the same reason).

**Lean:** A. It also composes cleanly with `decide()`'s existing halt/pause
gating — a step that can't resolve a required template input is a clean,
pre-flight HALT rather than a runtime crash mid-command.

## 4. Branching / conditional step selection

`FullPipeline` itself is pure-linear plus one QA halt gate — no real
existing recipe needs actual branching. Building a conditional/DSL engine
now, with zero real use cases demanding it, is the over-engineering trap.

**Lean (fairly confident):** ship linear-chain-plus-halt/pause first
(already 90% built via `decide()`), optionally add a narrow "skip this step
if `<file/condition>` already true" precondition (covers "don't re-import a
GDB that's already populated" without a general expression language). Defer
true branching until a real recipe actually needs it.

## 5. Reuse: `job_queue.py`'s CLOUD/HYBRID/LOCAL ordering

A recipe validator should reuse `job_queue.py`'s existing ordering logic to
warn (not silently reorder) when a recipe puts a LOCAL step before a CLOUD
step whose output it needs, or includes a LOCAL step with no `local_python`
configured for a headless run context. This is validation reuse, not new
design — the ordering rule already exists and is tested.

## 6. Migration path, not a rewrite mandate

Once a recipe format + data piping exist, `FullPipeline` becomes the first
acceptance test: express it as a recipe, confirm it round-trips (same steps,
same halt behavior, same stop-before-export checkpoint), and only then
consider whether the hardcoded `.pyt` class should delegate to it or stay as
is. Not urgent, not a step-1 requirement — `FullPipeline` works today.

---

## 7. Open questions for the user (mirrors §2.7's format — nothing here is decided)

1. Recipe format: YAML (config-style, Option A in §2) vs. Python registry
   (Option B) vs. defer until there's a second real multi-tool recipe to
   generalize from (right now there's exactly one: `FullPipeline`)?
2. Is data piping (§3) actually needed yet, or does every plausible near-term
   recipe (RTK import → CAD export, EDD import → screening → report) only
   need the *same* site/event/batch-id passed to every step, not one step's
   *output* feeding another's input? If the latter, a much simpler "shared
   named parameters" model may suffice without full output-binding templates.
3. Priority: is this worth building now, or does the GUI launcher (ADR-0057,
   currently the only real consumer of `Step`/`Workflow`) need more mileage
   first, per §2.6's original "prove the launcher before the builder" lean?
4. Should a recipe be allowed to mix CLOUD (headless) and LOCAL (arcpy)
   steps in one run, given LOCAL steps need a `local_python` interpreter the
   executor already requires callers to supply explicitly (ADR-0053)?

No implementation is proposed here — this is scoping for whoever picks up
the V2 workflow-builder work `2026-07-03-unified-gui-planning.md` §2.4
deferred, so that session starts from "these are the open design questions"
rather than from a blank page.
