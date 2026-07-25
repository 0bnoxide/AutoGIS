# AutoGIS — Claude Code session guide

## Default working mode — ponytail

**Every session must invoke the `ponytail` skill (full) before writing any code,
and keep it active for the session.** The skill is vendored in-repo at
`.claude/skills/ponytail/SKILL.md`, so it is available to cloud/remote agents and
any cloned checkout, not just user-scope installs. ponytail enforces the laziest
solution that actually works: question whether the change needs to exist (YAGNI),
reuse before writing, stdlib/native before dependencies, shortest correct diff
*after* understanding the problem. This applies to subagents too — state it in any
subagent prompt you write. It governs *what* you build, not how you talk, and never
shortcuts understanding the problem or skips validation/security/error handling.

## Codebase memory

The codebase-memory MCP server is **wired at USER scope** (stdio), not via a repo
file. The binary lives at
`C:\Users\ichbi\AppData\Roaming\npm\node_modules\codebase-memory-mcp\bin\codebase-memory-mcp.exe`
(npm-global install, on PATH as `codebase-memory-mcp`)
and is registered in `~/.claude.json` (`claude mcp add --scope user`). It is
**not** in the project `.mcp.json` — an earlier entry for it there pointed at a
non-existent npm package and was removed. The persistent index lives at
`~/.cache/codebase-memory-mcp/C-Users-ichbi-AutoGIS.db`.

> The project `.mcp.json` **does** exist now — it carries the **GitHub MCP**
> server only (`@modelcontextprotocol/server-github` via `npx`, token from the
> `GITHUB_PERSONAL_ACCESS_TOKEN` env var; the file holds no secret). That is a
> deliberate, working entry — do not "reconcile" it away. codebase-memory stays
> user-scope for the reasons above; the two are unrelated.

> **If the `mcp__codebase-memory-mcp__*` tools are missing this session:** the
> registration was likely wiped, or you just (re)registered and haven't restarted —
> MCP servers load at **startup only**. See `docs/codebase-memory-mcp.md` for the
> verified fix and the running deviation log. Until restarted, fall back to
> Grep/Glob/Read.

**At the start of every session (when the tools are present):**
1. Call `mcp__codebase-memory-mcp__index_status` (project `C-Users-ichbi-AutoGIS`).
2. If `status` is not `"ready"` or `nodes` looks stale (e.g. missing recent files),
   run `mcp__codebase-memory-mcp__detect_changes` then
   `mcp__codebase-memory-mcp__index_repository` before querying. (Markdown/ADRs are
   not indexed — the indexer scans Python only, so a docs-only change won't move the
   node count.)

Use the `/graph` skill to query the index. Key tools:

| Question type | Tool |
|---|---|
| Find a symbol / module / concept | `search_graph` |
| Find code by keyword or pattern | `search_code` |
| How does A call / depend on B? | `trace_path` |
| Layer / module overview | `get_architecture` |
| Fetch a specific snippet | `get_code_snippet` |

Fall back to Grep / Glob / Read / the Explore subagent when tools are absent
(web/cloud sessions) or when the index hasn't caught a very recent change.

---

## Project layout (quick reference)

| Path | Purpose |
|------|---------|
| `autogis/core/harvest/` | Attachment harvester — arcpy-free |
| `autogis/core/envmon/` | Environmental monitoring tools (derive live: `ls autogis/core/envmon/*.py \| wc -l`) |
| `autogis/core/common/` | Shared config, QA, logging, seen-index |
| `autogis/adapters/` | CLI (`cli.py`), `.pyt` toolbox, toolbox_core seam |
| `autogis/runtime/` | ArcGIS Pro session providers + capability guard |
| `autogis/config/` | Site configs, parser profiles, screening levels, figure specs |
| `tests/` | arcpy-free; run with `python -m pytest -q` (derive count live: `--collect-only`) |

## Key invariants

- `core/` and `adapters/` import with neither `arcpy` nor `arcgis` present.
- Tools 1, 9, 10 are headless (openpyxl only). Tools 2-8 are LOCAL (arcpy) — CLI
  commands for 2-8 guard then redirect to the `.pyt` toolbox.
- `HarvestConfig` is canonical in `core/common/config.py`; re-exported from
  `core/harvest/models.py` for back-compat.
- Screening levels and the H281 parser profile are pre-production stubs — do not
  remove DRAFT banners or `_TODO` markers until verified against real data.
- **arcpy IS runnable on this machine** — not in the dev venv (arcpy is
  Pro-conda-only), but ArcGIS Pro 3.6.1 is installed and a cloned env
  (`%LOCALAPPDATA%\ESRI\conda\envs\arcgispro-py3-autogis`) has AutoGIS
  editable-installed. Use it for live arcpy QA (`python -m autogis` +
  PYTHONPATH for worktrees); the test suite stays on the arcpy-free dev
  venv. Full how-to + rebuild-after-Pro-upgrade: `docs/arcpy-environment.md`.
- **arcpy calls MUST be doc-verified before shipping** (ADR-0077). Any new or
  edited arcpy call — including `.pyt` parameter/filter objects and reviewer-
  proposed fixes — gets its signature, keywords/enums, and deprecation status
  checked against current Esri docs (pro.arcgis.com tool reference) in the same
  session that writes it; cite the pages in the PR. Compliance floor is ArcGIS
  Pro **3.5** (prefer 3.6/3.7): anything deprecated at 3.5 is banned. Training-
  data recall of arcpy signatures is not evidence — the suite cannot catch these
  (arcpy seams are `pragma: no cover`), which is how #174/#214 shipped.
- **Found a bug → file a GitHub issue for it, regardless of task.** Applies to
  every session and every subagent (state it in subagent prompts). A "bug" is a
  real defect in committed code/config: wrong behavior, crash, data loss, silent
  no-op/false-success, unhandled edge, security, or an incorrect/deprecated arcpy
  call. If you discover one — even if you can't fix it now, even if it's off-topic
  from what you're doing — file it through an available GitHub write path
  (`/new-issue`, the Codex GitHub connector, or `gh issue create`) so it gets
  proper follow-up. Check existing open+closed issues first to avoid duplicates.
  If the session has no issue-creation tool or authentication, do not halt the
  active task: provide a complete ready-to-file issue draft in the handoff/final
  response, mark it **unfiled**, and require the next tool-enabled session to
  file it. Otherwise, do **not** leave a discovered bug recorded only in a
  decision log, PR comment, memory, or the collab channel.

## Deferred tool groups — phase-gate status

Deferred groups are **out of scope until a deliberate phase-gate decision reopens
them.** Do not implement, spec, or fast-track a deferred group without the user
explicitly re-opening it first:

- **AI-assisted (§11) — DEFERRED:** `AIDraftParserProfile`, `AIExplainQAReport`,
  `AIDraftFigureSpec`, `AIMapReviewChecklist` — deferred pending LLM seam design
  (`docs/superpowers/specs/2026-06-28-ai-assisted-tools-llm-seam-design.md`).
  Binding until the user says otherwise — not a backlog to pick from when idle.
- **Conditional / geostatistical (Phase 5) — GATE CLOSED, SHIPPED:** the
  required architecture review landed as **ADR-0085 (Accepted 2026-07-16)** and
  both slices merged the same day — slice 1 (TIN/IDW pipeline, GW_ModelRun
  registry, plume clip; PR #240) and slice 2 (EBK, uncertainty raster,
  concentration surface, nondetect policy; PR #241, **ADR-0086 Accepted
  2026-07-24** — user sign-off). All 3 tools exist
  (RunFieldToGroundwaterModelPipeline, BuildGroundwaterSurfaceModel,
  BuildAnalyticalConcentrationSurface). **Residual: live-Pro EBK/GA acceptance
  run is pending owner QA** — workflow + synthetic data in
  `docs/qa/geostat-live-pro-qa.md`. Do not re-freeze this group; the
  2026-07-15 handoff (`docs/HANDOFF-2026-07-15-geostat.md`) describes the
  pre-acceptance state and is historical. The other 6 tools originally
  reviewed as conditional shipped earlier — see issue #167 and ADR-0061.

Other roadmap batches have been quietly fast-tracked before without a formal gate
decision — treat "deferred"/"blocked" as binding until the user says otherwise, and
record every gate change (like the 2026-07-15 reopening above) in this section.
Gate changes: 2026-07-15 — geostat group reopened (user); 2026-07-16 — ADR-0085
accepted, slices 1+2 merged; 2026-07-24 — ADR-0086 accepted (user sign-off),
gate closed with live-Pro QA leg pending owner availability.

## Post-catalog production roadmap

The user accepted the complementary-capabilities production sequence on
2026-07-16. [`docs/production-roadmap.md`](docs/production-roadmap.md) is the
authoritative living roadmap; ADR-0087 records the ordering decision. Each
capability owns one production phase and must meet its exit gate before the next
phase starts. Do not reorder or parallel fast-track phases without an explicit
user decision. This roadmap does not reopen any deferred group above.

Gate changes (record each here): 2026-07-19 — Phase 1 gate's "Pro 3.5 + current
release" leg amended to "currently installed Pro release" (user decision,
ADR-0091); 3.5-floor compliance stays an authoring-time ADR-0077 duty.
2026-07-20 — Phase 2 shipped (ADR-0093, owner sign-off). 2026-07-22 — Phase 3
first slice shipped (ADR-0102); Phase 4 shipped (ADR-0105, owner sign-off);
Phase 5 shipped in two slices (ADR-0103/0104). 2026-07-23 — Phase 6 shipped
(ADR-0107); Phase 7 slice 1 shipped (ADR-0108, historical-events acceptance
leg owner-gated — "acceptance pending"); Phase 8 slice 1 shipped
(ADR-0109, validator leg owner-gated). 2026-07-24 — Phase 9 slice 1 shipped
(ADR-0111); its live-sandbox gate run stays owner-gated (issue #307). Phase 10
(portfolio digest) has not started — no ADR yet.

## Decision records

Two separate records — easy to conflate, keep both:

- **ADRs** (`docs/adr/NNNN-*.md`): the durable record of any architectural /
  structural / invariant / **tool-batch** decision. Ship a batch or make a design
  call → add an ADR (`/new-adr`; format in `docs/adr/README.md`). This is the
  "regular" logging and it is **required** — it lapsed for the 2026-06-29/30
  batches and had to be backfilled (ADR-0030/0031).
- **Agent-decision logs** (`docs/adr/logs/YYYY-MM-DD-agent-decisions.md`): an audit
  of the agent's *autonomous judgment calls* ("free will"). A **supplement** to
  ADRs, **not** a substitute — logging a judgment call does not discharge the ADR,
  and these logs live only in `docs/adr/logs/` (not a parallel path). See
  `docs/adr/logs/README.md`.

## Worktrees & session coordination

- **`main` is READ-ONLY — branch before you write.** On `main` only *reading* is
  permitted. Every write (Edit/Write/MultiEdit/NotebookEdit to a repo file;
  `git commit`/`merge`/`rebase`/`cherry-pick`/`revert` on main; any `git push`
  whose refspec targets remote `main`, from any branch) is **denied** by the
  PreToolUse coordination hook
  (`hook_check.py`); writes to paths *outside* the repo — your memory dir, the
  scratchpad — are exempt. Before any work: check out a feature branch and claim
  it + your files via the coordination framework below. **This rule applies to
  subagents too:** the hook fires for every tool call regardless of caller, so it
  is enforced even for built-in agents — but state it explicitly in any subagent
  prompt you write. One-off override: `AUTOGIS_COORD_FORCE=1` — must be exported
  into the process environment *before* the session/hook launches (e.g. set in
  the shell that starts Claude Code). An inline per-command prefix like
  `AUTOGIS_COORD_FORCE=1 git commit ...` cannot reach the hook — `hook_check.py`
  runs as its own process and reads its own `os.environ`, not the command's. For
  pinned-cwd subagents (which can't export env before launch), use
  `python .claude/coordination/coord_cli.py whoami|release-mine|resync` instead
  — these resolve the session id via `--session` / `$AUTOGIS_SESSION_ID` / a
  cwd-claim fallback, not the FORCE bypass. The SessionStart hook also
  fast-forward-pulls a clean `main` so every session (and the worktrees that
  branch from HEAD) starts current.
- **The hook resolves the write's branch/tree from the *target*, not payload
  `cwd`** (fixes #136 bug 1a). A pinned-cwd subagent whose `cwd` is frozen at the
  main root is judged by where the write actually lands — the edited file's dir,
  or the `git -C <wt>` / `cd <wt> && …` dir of a git write — so a legitimate
  worktree commit is no longer false-denied. Ceiling (safe direction): exotic
  Bash (subshells, `$vars`) and non-POSIX Windows paths fall back to `cwd`; the
  `git -C C:/…` form always resolves. The hook also emits a **soft, non-blocking
  warning** on an in-repo write when another live session shares this main tree
  and the write targets it — a re-nudge to isolate (it never blocks).
- **Worktrees live under `.claude/worktrees/`** (gitignored), not the
  `superpowers:using-git-worktrees` default `.worktrees/`. Prefer the native
  `EnterWorktree` tool (Step 1a); if you ever fall back to `git worktree add`,
  target `.claude/worktrees/<branch>`.
- **One shared claim registry.** The session-coordination registry
  (`.claude/coordination/claims.json`, gitignored) always lives at the **main**
  working tree's root. `registry.claims_path()` resolves it via
  `git rev-parse --git-common-dir`, so a worktree session and the main checkout
  share one registry — never a per-worktree copy.
- **`EnterWorktree` mid-session doesn't fire `SessionStart`.** The auto-claim
  only runs at session start, so after switching into a worktree mid-session the
  session still holds its *old* branch/worktree claims (the PreToolUse heartbeat
  keeps refreshing them) and has *not* claimed the new branch. Left as-is this
  both (a) falsely locks the old branch against other sessions and (b) can make
  the hook deny you committing to the branch you just moved to (if another
  session claimed it). After `EnterWorktree`, **run `resync`** — it releases
  the old branch/worktree claims (preserving any in-flight `file_glob` claims,
  #159) and reclaims the new ones in one step, using the canonical coordination
  dir at the main root:

  ```bash
  COORD="$(git rev-parse --git-common-dir)/.."   # main tree root
  python "$COORD/.claude/coordination/coord_cli.py" resync --session "$SESSION_ID"
  ```

## Claude↔Codex shared-memory channel

Claude Code and Codex share context through the Mnemoverse domain
**`collab:autogis`** (both agents, one account). The shared `SessionStart`
hook automatically runs the three targeted queries — `STATUS handoff`,
`BLOCKER`, `DECISION` — and injects bounded, deduplicated results before work
starts. If it reports retrieval unavailable and the Mnemoverse MCP tools are
present, run those three reads manually. Write on handoff/decision/blocker per
the canonical protocol in **ADR-0095** (message types, GitHub-first routing,
supersession/filtered-write mechanics); read it before writing to the channel.
Context only: the channel never locks anything (locking = coordination hook +
ADR-0094 shim), and GitHub/repo remain source of truth. No API key/tools in a
cloud/web session means skip; startup remains fail-open by design.
