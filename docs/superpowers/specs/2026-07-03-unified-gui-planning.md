# Unified GUI — architecture overview & planning brainstorm

**Status:** direction decided (2026-07-04), no code yet. **Date:** 2026-07-03.
**Revision:** v2, after a full adversarial Fable review (appended below)
found 4 HIGH-severity issues in v1 — all corrected here.

**All 6 open questions in §2.7 were answered by the user on 2026-07-04 —
see [ADR-0050](../../adr/0050-unified-gui-adapter-direction.md) for the
decisions and their rationale.** Short version: standalone PySide6 app,
added as a new adapter in this repo (not a fork, not a separate repo);
audience is existing Pro users only; v1 scope includes both the tool
launcher and the workflow/pipeline builder together; concurrent multi-analyst
use is real and must be handled in v1; run-history writes hook at the CLI
seam with concurrency-safe writes. The brainstorm below is kept as the
reasoning trail — read ADR-0050 first for the actual decisions.

AutoGIS just closed its entire ~79-tool roadmap (README's "Planned" and "Not
started" sections are both empty as of this doc). This opens a new chapter:
tying the ~105 CLI commands together behind one GUI, with generalized
workflow/pipeline wiring between tools. This doc has two parts: **Part 1**
recaps the current architecture as it bears on GUI planning (facts, verified
against code). **Part 2** is the brainstorm — options, a reuse plan, and open
questions for later review. Nothing here is decided; §2.7 is the actual ask.

---

## Part 1 — Current architecture, as it bears on GUI planning

### 1.1 Three adapters over one core

`autogis` ships one arcpy-free `core/` behind three adapters: a `click` CLI
(`adapters/cli.py`, ~4000 lines, 105 leaf commands under `envmon`/`agol`
groups plus `harvest`), an ArcGIS Pro `.pyt` toolbox (`adapters/toolbox.pyt`,
~700 lines, today the only thing anyone would call a "GUI"), and the core
itself as an importable library. A fourth adapter (a unified GUI) is what
this doc plans for.

### 1.2 The runtime split — CLOUD / HYBRID / LOCAL, and what actually gates on it

`runtime/capabilities.py`'s `TOOLS` dict is the **guard registry**, not a
classification of every tool: it has **70 entries** against 105 leaf
commands. `guard.py`'s `require_runtime()` checks `requires_arcpy(name)`
against it and raises `RuntimeUnavailable` for LOCAL tools with no arcpy
present — but `requires_arcpy()` raises a bare `KeyError` for any of the
~35 commands absent from `TOOLS` (`capabilities.py:85-91`), so a GUI cannot
use `TOOLS` alone as "can this run here" for the whole palette. The broader
classification surface is `_REGISTRY_SEED` (see 1.4), with its own coverage
gap.

### 1.3 The LOCAL split that matters most for a GUI — and where it's actually unreachable

Two ADRs govern this:

- **ADR-0006** (2026-06-20): the original 8 LOCAL tools (2-8) have the `.pyt`
  toolbox as their **only** UI. After `_guard()` passes — even with arcpy
  present — the CLI **unconditionally raises `ClickException`** for 6 of
  them: `import-gdb`, `build-event`, `build-callouts`, `gw-contours`,
  `export-figures`, `full-pipeline` (verified directly in `cli.py`). This is
  a **deliberate policy choice**, not a technical wall — `arcpy_env()`
  resolves identically regardless of caller. **Exceptions:** `validate-db`
  (nominally "tool 8") actually executes `validate_database(...)` directly,
  no exception raised (`cli.py:1466-1483`); so does `harvest` (registered
  `HYBRID`, never gated LOCAL-only).
- **ADR-0039** (2026-07-02): LOCAL tools added *since* ADR-0006 are
  **CLI-first** by default — run directly via a cloned `arcgispro-py3` conda
  env, no `.pyt` entry needed unless interactive map context is required.

**Correction from v1 (Fable review H2): reachability is not "6 blocked, ~75
reachable."** ADR-0039's own body — half of it, easy to skim past — scopes
out **three more tool families that are unreachable in *every* environment**,
not just headless:

- `optimize-callouts` (Tool 5.2) — guards, then unconditionally raises; no
  `.pyt` class exists either (`cli.py:1326-1339`). Superseded by an
  unimplemented `--use-hull-collision` flag design on `build-callouts`.
- `manage-callout-overrides` (Tool 5.3) — all 4 subcommands (`list`, `clear`,
  `lock`, `unlock`) guard then raise; no `.pyt` class either
  (`cli.py:1352-1424`). Core CRUD exists and is arcpy-tested, but CLI wiring
  is blocked on a missing "read one full override" function.
- `build-cad-package` (Tool 8.9) — guards then raises: *"requires ArcGIS Pro
  … and has no .pyt toolbox entry yet — see issue #105"*
  (`cli.py:3941-3954`). **v1 wrongly cited this as a working CLI-first
  generation-2 example** (an error inherited from ADR-0039's own context
  section, which lists it among tools that "execute the real work in the
  CLI" — true of the module import, false of the command). Corrected here.
- `export-civil3d --landxml` (Tool 8.2, partial) — the flag routes to the
  same "no `.pyt` entry" dead end (`cli.py:3971-3975`); the PNEZD-CSV path
  (no flag) is genuinely headless and works.

All four families are marked `status: "stable"` (or `"planned"` for
build-cad-package) in `_REGISTRY_SEED` (1.4) — a palette built naively from
that registry would render launchable buttons that always error.

**Corrected reachability summary:** 6 tools Pro-fallback-only by policy
(ADR-0006) · 4 tool families (7 leaf commands) unreachable in any environment
by incomplete implementation (ADR-0039's scoped dead ends) · everything else
(~90 commands) reachable via CLOUD execution or shelling into
`arcgispro-py3`.

### 1.4 The existing reuse spine

Four pieces already do much of the structural work a "tie it all together"
GUI needs — with real gaps:

1. **`_REGISTRY_SEED` / `TOOL_REGISTRY`** (`runtime/capabilities.py`) — ~95
   entries with `(command, name, roadmap_id, runtime, status, domain,
   description)`, grouped by `domain` (intake, qa, analysis, cartography,
   field, agol, reporting, admin). **Correction from v1: this covers `envmon`
   commands only.** `harvest` and all 9 `agol` commands (`publish-layer`,
   `audit-schema`, `promote`, `sync-to-gdb`, etc.) have no entry — confirmed
   by the drift-guard test itself, which only walks the `envmon` group
   (`tests/test_capabilities.py:26-36`). A palette built from this list today
   would be missing the entire AGOL surface, which a workflow-wiring GUI
   would specifically care about.
2. **`job_queue.py`** (Tool 10.4, `generate_job_queue`) — builds an ordered
   `JobEntry` list (tool × site, CLOUD→HYBRID→LOCAL) from a manifest.
   **Gap: generates the plan only.** No runner executes a `JobEntry` list
   anywhere in the module, its tests, or any caller.
3. **`run_history.py`** (`RunRecord`/`RunHistory`, CSV-backed, ADR-0017) —
   the audit schema a GUI's run-status view would read. `RunHistory.write()`
   has exactly **one** production caller: `core/agol/promote.py:125`
   (`_log_promotion`), wired from the `agol promote` CLI command
   (`cli.py:1939-1970`) — shipped after the 2026-07-01 architecture review
   flagged it as completely unwired (finding H1). Write path: unlocked,
   best-effort CSV append (`run_history.py:89-101`); the per-instance read
   cache invalidates on write within one process but is stale across
   processes.
4. **`FullPipeline`** (`.pyt` Tool 7, `toolbox.pyt:527-607`) — the
   workflow-wiring precedent. It deliberately **stops before export** —
   *"kept separate so layouts can be reviewed first"* — a built-in
   human-review breakpoint. Only the **import-stage** QA check halts
   (`if qa_status == "FAIL": return`); the per-figure-spec loop reports QA
   but never gates on it. (Note: the class's own docstring says "QA gates
   between stages," which overstates its own code — don't import `.pyt` tool
   descriptions into a GUI verbatim without checking them against behavior.)

Plus `runtime/sessions.py`'s three lazy session providers
(`agol_from_profile`, `pro_active_portal`, `arcpy_env`) — the right shape for
a GUI to manage credentials without forcing an import cost on tools that
don't need one.

### 1.5 What's genuinely not there yet

- No GUI or web framework dependency anywhere in the repo. Framework choice
  is open (but see 2.2 — not literally greenfield; a candidate doc already
  compared options).
- No job executor / task runner of any kind.
- **A dormant progress/cancel scaffold that doesn't fit a subprocess
  executor.** `core/common/reporting.py`'s `Reporter` class has
  `cancel()`/`emit_progress(done, total)` hooks, but zero production callers
  and zero callers of `emit_progress` even in its own test
  (`tests/test_reporting.py:17` only exercises the cancel hook). It's a
  cooperative in-process callback contract — structurally the wrong shape
  for a standalone GUI shelling to a subprocess (progress there is
  stdout/exit-code, not a shared object), and adopting it in-process would
  mean threading a `reporter` param through ~100 core functions, the same
  mass-retrofit problem run-history has. Not a building block to resurrect;
  a job-level status model (queued/running/done + exit code) needs no tool
  cooperation and fits either fork.
- `pyproject.toml:13-15` already defines two console-script entry points
  (`autogis`, `autogis-harvest`) in the one pip-installable package — the
  natural slot for a third (`autogis-gui`), not a separate install story.
- `arcpy` is only importable where a **licensed** ArcGIS Pro installation is
  cloned into a conda env — this is a hard licensing wall, not a
  configuration detail. Nothing in this stack lets a Pro-unlicensed machine
  run LOCAL tools, under any GUI design.

---

## Part 2 — Brainstorm

**Correction from v1: this is not a greenfield chapter.**
`docs/candidates/boring-survey-drone-level-automation-roadmap.md` §3 ("GUI
Implementations", lines 365-491) already contains a GUI plan: a recommended
"thin shell over the same Python core used by CLI/`.pyt`/AGOL" architecture,
a 6-framework comparison table (PySide6/PyQt, Tkinter, Streamlit, NiceGUI,
ArcGIS Python Toolbox, Experience Builder/Dashboards), a named launcher
concept ("Project Automation Hub," 8 tabs including a Run History tab), an
implementation feature checklist (progress bar, live log, QA table, dry-run,
save/load run profiles, "Open in ArcGIS Pro" button), and a job-manifest YAML
pattern with `run_id`/`workflow`/`inputs`/`outputs`/`settings` fields. This
doc independently converges on the same "thin shell, shared core" direction
below — it should be read as a prior planning pass to build on, not
re-derived. Its framework table and feature list feed directly into open
questions 3 and 4.

### 2.1 The lead question: who uses this, where do they sit

Not the fork below — that's downstream. **Do the users already have ArcGIS
Pro seats?** Sharpened per licensing (1.5): field staff, PMs, or clients
without a Pro license can *never* run LOCAL tools under any GUI design —
Pro's license, not the GUI's architecture, is the wall. So the real question
is "does anyone without a Pro seat need this, and is CLOUD-tool-only access
acceptable for them?" A yes commits the design to a two-tier capability UX
(full toolset for Pro-seated users, CLOUD-only subset for everyone else),
which is a bigger decision than a simple standalone-vs-embedded choice.

### 2.2 The fork: where does the GUI run — three-way, not two

**Correction from v1: "embedded in Pro" is not one option.** A persistent
custom dockable pane in ArcGIS Pro is built on the ArcGIS Pro SDK for
**.NET/C#** — a language this repo has zero lines of, and one
`docs/repo-integration-roadmap.md:37` already ruled out for a past feature
("wrong language & runtime for a Python framework"). Python's only
supported "inside Pro" surfaces are script tools / Python toolboxes (what
`.pyt` already is) and the Pro Python window/notebooks — none support a
persistent custom panel. The real fork:

- **A. Standalone** (desktop or local web app) — invokes CLOUD tools
  directly and generation-2 LOCAL tools by shelling into `arcgispro-py3`.
  The 6 ADR-0006-blocked tools and 4 dead-end families (1.3) stay
  unreachable unless those decisions are separately reopened. Reaches
  non-Pro-seated users for CLOUD tools only (2.1).
- **B. Grow the existing `.pyt`** — genuinely "embedded," Python-native, zero
  new language. But this is not a new GUI with cross-tool wiring beyond what
  `FullPipeline` already hand-builds; it's extending what's already shipped,
  and the prior architecture review flagged it as an undertested inline
  marshalling pattern (finding M2) even before adding orchestration to it.
  Unusable by non-Pro-seated users at all.
- **C. A .NET/C# Pro add-in** — reaches full capability with a persistent
  dockable pane, but is a new language/toolchain for this project, with the
  precedent above already against it.

"Embedded is simpler if the audience is Pro-only" (v1's lean) is only true
for **Option B** — and B is "keep extending `.pyt`," a materially different
answer than "build a new embedded GUI," which is what Option C would
actually be.

### 2.3 Two research findings that shape the MVP

**Auto-generating per-tool forms is ~80% mechanical, not fully generic.**
Sampled ~35 commands across every domain: only the harvester takes a single
config-file input; every other tool mixes positional file args, repeatable
options, `Choice` enums, comma-split string options (`--analytes "a,b,c"`),
mutual-exclusion pairs (`--wells-csv` xor `--gdb`), output format chosen by
file extension, and ~13 report-producing commands that hardcode `fail_on`
with no CLI option at all. Click's own parameter introspection covers most
of this mechanically; the exceptions above need hand-tuning. The **output**
side is more uniform: most CLOUD tools build a `QACollector` ending in
`_render_qa(qa, report, fail_on)` (79 call sites; 35 via a shared
`qa_report_options` decorator, the rest declared by hand under a tested
shared contract) — a generic "QA result" display component is more feasible
than a generic input form. **Lazy MVP fallback:** hand-built forms for the
dozen highest-traffic tools, a raw-args box with saved presets for the long
tail, rather than chasing one fully generic form generator.

**No per-tool progress plumbing exists to build on (1.5).** MVP status
should be job-level — queued / running / done + exit code, read from
subprocess exit + written QA files — which needs no cooperation from
existing tool code and is consistent with how every tool behaves today
(load → compute → write → return, once).

### 2.4 Workflow wiring, generalized from `FullPipeline` — explicitly V2, not MVP

"Wiring like full-pipeline" = an ordered list of (tool, args) steps, reusing
`job_queue.py`'s CLOUD→HYBRID→LOCAL ordering, run by an **executor** that
checks each step's status and can halt (mirroring `FullPipeline`'s one real
gate), and supports a **"pause for human review" step type** —
`FullPipeline`'s deliberate stop-before-export already proves this pattern is
needed; generalize it rather than lose it. **This is V2 scope.** The MVP
launcher (2.3) needs only `subprocess.run` + exit code + QA-file display;
CLOUD→HYBRID→LOCAL ordering, halt gates, and pause-for-review are
workflow-builder concerns that shouldn't gate the first milestone.

### 2.5 Run-history: fix the seam that exists today, don't wait for the executor

**Correction from v1 (Fable review H3): "executor as sole run-history
writer" was the wrong design.** It creates two audit-log philosophies (GUI
runs logged, today's CLI/scripted runs not — the log becomes a GUI activity
log, not the "every execution" contract ADR-0017 states), and it
double-logs `agol promote`, which already writes its own record — the
executor wrapping it would produce two records per promotion. **The lazier,
correct fix already has a name**: the 2026-07-01 architecture review's H1
recommendation — one result-callback wired at the CLI adapter seam
(`cli.py`), covering every CLI invocation regardless of caller. This needs no
executor and no GUI; it fixes `evaluate-readiness`/`portfolio-metrics`
(shipped readers of a still-mostly-empty log) now, and a standalone GUI gets
working history for free the moment it shells the CLI. Under this design a
V2 executor needs no writer of its own for single-tool steps (only possibly
a workflow-level record for a multi-step run as a unit).

This also reframes the concurrency risk: `run_history.write()` is unlocked,
best-effort CSV append with no cross-process cache invalidation (1.4). If the
write hook lands at the CLI seam, **any concurrent CLI usage races**, GUI
launched or not — not just "two people using the GUI at once" (v1's framing).
Whether that race needs solving now depends on open question 6.

### 2.6 Tentative lean (arguable — this is what both reviews were for)

Answer 2.1 (audience/licensing) first. MVP = tool launcher (Option A or B
per 2.2, decided by audience) + generic QA-result display + mostly-generic
arg forms with hand-built fallback for irregular commands (2.3) + job-level
status only, no per-tool progress. Fix the run-history CLI-seam callback
(2.5) as its own small, separately-valuable change — it stands on its own
merit regardless of what happens with the GUI. Workflow/pipeline
builder — with pause-for-review — is V2 (2.4), built only once the launcher
is proven. `docs/candidates/boring-survey-drone-level-automation-roadmap.md`
§3's framework table and 8-tab feature list are a running start for V2
scope, not something to re-derive. Defer the ADR-0006 reopen question and
the two other dead-end tool families (1.3) explicitly rather than assuming
an answer.

### 2.7 Open questions for later review

1. **Who is the user, and do they sit in Pro?** Sharpened: is CLOUD-tool-only
   access acceptable for anyone without a Pro seat, or does everyone who'd
   use this have a license?
2. **Which of the three options in 2.2** — standalone, grow-the-`.pyt`, or a
   .NET/C# add-in — and if standalone: is reopening ADR-0006 (headless path
   for the 6 Pro-fallback tools) or finishing the 4 dead-end tool families
   (1.3) in scope, or do they stay "open in Pro" links / stay broken?
3. **Framework**, informed by the candidate doc's comparison table (§3.2) —
   contingent on #1/#2, and constrained by needing to pip-install cleanly
   into a `arcgispro-py3` conda clone on Windows if full capability matters.
4. **MVP scope** — launcher only (2.3/2.6), or launcher + workflow builder
   (2.4) in the same first milestone? The candidate doc's 8-tab "Project
   Automation Hub" concept is a useful checklist either way.
5. **Single-user local tool vs shared/multi-user deployment** — decides
   whether the run-history race (2.5) needs solving now (file lock, or move
   writes behind a small local service) and whether auth/concurrent-job
   locking are in scope at all.
6. **Where does the run-history write hook live** — a CLI-seam callback
   (fixes today's dead readers immediately, no GUI required, recommended
   default per 2.5), a future executor, or both with dedupe against
   already-self-logging commands like `agol promote`?

---

## Verification trail

Facts verified by direct code read across two passes (v1: `cli.py` LOCAL-tool
guard blocks, `guard.py`/`sessions.py`, `job_queue.py`, `run_history.py` +
`promote.py` caller, `FullPipeline`'s class body, `reporting.py`'s dormant
`Reporter`, ADR-0006, ADR-0039, a ~35-command Click parameter-shape sample;
v2 corrections: `optimize-callouts`/`manage-callout-overrides`/
`build-cad-package`/`export-civil3d --landxml` guard blocks, `TOOLS` dict
entry count vs. command count, `_REGISTRY_SEED`'s envmon-only coverage, and
`docs/candidates/boring-survey-drone-level-automation-roadmap.md` §3). Two
Fable passes reviewed this: a quick direction gut-check (3 corrections,
folded into v1) and a full adversarial architectural review (4 HIGH + 5
MEDIUM + 4 LOW findings against v1, folded into this v2 — full text below).
Every HIGH finding in the review below was independently re-verified against
source before being applied, not taken on citation alone.

---

## Appendix: full Fable architectural review (against v1, verbatim)

**Reviewer:** independent adversarial pass (Fable 5), 2026-07-03.
**Subject:** `gui-planning-draft.md` v1, the opening document of the
unified-GUI planning chapter.
**Method:** every load-bearing claim re-verified against current code on
`main` — no claim trusted from the draft, prior passes, or ADR text.

### Verdict in one paragraph

Part 1 is mostly accurate and usefully framed, and Part 2's instincts
(audience-first, MVP-launcher-then-workflows, defer the framework) are the
right shape. But the draft has one flatly false premise (the "genuine
greenfield, no prior GUI planning" claim — the repo contains a whole prior
GUI section, framework table and all), one inherited factual error that
corrupts its central reachability math (`build-cad-package` cited as
CLI-first when it is a dead end in every environment, plus three omitted
dead-end tool families), one design position that contradicts the standing
architecture-review recommendation it cites (executor as sole run-history
writer), and one missing fact that likely flips the user's answer to the
standalone-vs-embedded fork (a Pro dockable pane means C#/.NET). None of
these is expensive to fix; all four would send the user's answers to the
open questions in the wrong direction if handed over as-is. Notably, both
errors that trace to documents (ADR-0039's tool list, the greenfield claim)
survived two prior review passes — the draft verified code claims well and
document claims poorly.

### HIGH

**H1. [Factual] "No prior GUI/launcher planning exists" is false.**
`docs/candidates/boring-survey-drone-level-automation-roadmap.md` lines
365-491 contain a full "GUI Implementations" section: a recommended
thin-shell-over-shared-core architecture (3.1), a six-framework comparison
table (3.2), a named launcher concept "Project Automation Hub" with 8 tabs
including a Run History tab (3.3), and an implementation feature list plus
job-manifest YAML pattern (3.4). The reconciliation is favorable — the prior
doc endorses the same direction — but the draft must build on it, not claim
vacuum.

**H2. [Factual] Reachability math is wrong; `build-cad-package` miscited as
CLI-first.** Beyond the 6 ADR-0006-blocked tools, three more tool families
are unreachable in *every* environment: `optimize-callouts`,
`manage-callout-overrides` (4 subcommands), and `build-cad-package` (plus
`export-civil3d --landxml`) — all guard-then-raise with no `.pyt` fallback
either, per ADR-0039's own scoped-dead-ends section. The draft affirmatively
lists `build-cad-package` as working CLI-first (inherited from ADR-0039's
context section, which makes the same error about the module import vs. the
command). The discovery registry marks these `"stable"`, so a palette
built naively from it renders always-broken buttons.

**H3. [Logic] "Executor as sole run-history writer" creates two audit-log
philosophies and double-logs `agol promote`.** If only the future executor
writes history, every non-GUI (i.e., today's only interface) run writes
nothing — the log becomes a GUI activity log, not ADR-0017's "every
execution" contract. And wrapping `agol promote` (which already
self-logs via `_log_promotion`) would double-write. The 2026-07-01
review's H1 recommendation (one CLI-seam callback) already covers this
correctly and was cited as provenance, then silently replaced with a worse
design.

**H4. [Completeness] "Embedded in Pro" hides a language fork.** A persistent
Pro dockable pane requires the ArcGIS Pro SDK for .NET/C# — zero lines of
which exist in this repo, and which `docs/repo-integration-roadmap.md`
already rejected for a past feature on the same grounds. The real fork is
three-way: standalone / grow-the-existing-`.pyt` / a new .NET add-in — not
"standalone vs. embedded."

### MEDIUM

**M1.** `Reporter` (`core/common/reporting.py`) is a cooperative in-process
callback contract, structurally wrong for a subprocess-based standalone
executor and a mass-retrofit for an in-process one; recommend cutting the
"resurrect it" idea in favor of job-level status. (Nit: it's not *never*
instantiated — a test exercises the cancel hook; `emit_progress` genuinely
has zero callers anywhere including tests.)

**M2.** `TOOLS` has 70 entries against ~105-110 commands and is the guard
registry, not a full classification — `requires_arcpy()` KeyErrors on
absent entries. `_REGISTRY_SEED` (~95 entries) is the right classification
surface, with M3's caveat.

**M3.** `_REGISTRY_SEED` covers `envmon` only — `harvest` and all 9 `agol`
commands (including `promote`, `sync-to-gdb`, `publish-layer`) have no
entry, confirmed by the drift-guard test walking only the `envmon` group.

**M4.** Licensing and distribution are absent from the draft. `arcpy`
requires a licensed Pro install — no GUI design lets non-Pro-licensed users
run LOCAL tools; this sharpens open question 1. `pyproject.toml` already
defines console-script entry points — the natural distribution path for a
GUI is a third entry point in the same package, not a separate installer.

**M5.** The run-history race (2.5/1.4) shouldn't be conditioned on
multi-user GUI use — a single user's parallel jobs already race, and if the
write hook lands at the CLI seam (H3's fix), any concurrent CLI usage races
regardless of the GUI.

### LOW

**L1.** The "wrong language & runtime" quote in
`docs/repo-integration-roadmap.md:37` was about a C#/.NET repo, not the
dropped JS web app (a different line) — the inference for H4 still holds,
just cite the right line.

**L2.** ~105 leaf commands (105 command decorators, one of which is a group
with 4 subcommands), not ~107 — refresh the baseline count when this
becomes a repo doc.

**L3.** `qa_report_options` covers 35 of 79 `_render_qa` call sites; the rest
declare `--report`/`--fail-on` by hand under a tested shared contract
(`test_qa_report_commands_share_fail_on_contract`) — conclusion (generic QA
display is feasible) unchanged, but ~13 commands hardcode `fail_on` with no
option at all, one more heterogeneity bucket for the form generator.

**L4.** `FullPipeline`'s own docstring ("QA gates between stages") overstates
its actual code (one real gate) — a GUI must not import `.pyt` tool
descriptions verbatim without checking them against behavior.

### Ponytail / scope check

Mostly right-sized for early planning (MVP-then-V2, framework/ADR-0006
reopen deferred). Three over-engineering leaks flagged and corrected in v2:
(1) coupling the run-history fix to an executor that doesn't exist yet
instead of using the already-available CLI seam; (2) "resurrect `Reporter`"
drags in a per-tool cooperation contract neither fork can use; (3) the
workflow-wiring executor sketch needed an explicit "this is V2, not MVP"
label — the MVP launcher needs only `subprocess.run` + exit code + QA-file
display.

### Readiness

Not ready as v1; required a revision pass covering all four HIGH findings
plus the MEDIUM factual corrections. This document (v2) is that revision.
