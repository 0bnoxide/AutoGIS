# ADR-0094: Codex coordination shim — reuse `hook_check.decide()` across harnesses

**Status:** Accepted

**Date:** 2026-07-20

## Context

The session-coordination framework (`.claude/coordination/`) enforces the
read-only-`main` and claimed-file/branch invariants through a **Claude Code
`PreToolUse` hook** (`hook_check.py::decide()`). That hook only intercepts
tool calls made *inside the Claude Code harness*. As Claude↔Codex collaboration
on this repo begins (shared context channel: Mnemoverse domain `collab:autogis`),
Codex runs in a different harness where `hook_check.py` never fires — so
`claims.json` and the read-only-`main` rule bind Claude but are merely advisory
for Codex. Codex could commit to `main` or overwrite a file another session
claimed with nothing stopping it.

Codex does support custom `PreToolUse` **command** hooks whose contract is the
same shape as Claude Code's: a JSON tool-call payload on stdin, a
`hookSpecificOutput`/`permissionDecision` verdict out (or exit 2 + stderr), and
the ability to block or rewrite the call
(https://learn.chatgpt.com/docs/hooks, retrieved 2026-07-20).

## Decision

Add `.claude/coordination/codex_coord_shim.py` — a thin adapter that Codex's
hook invokes — which **reuses `hook_check.decide()` verbatim** rather than
reimplementing the branch/claims rules in PowerShell or JS. `decide()` stays
the single source of truth; a second copy would drift from it (the logic has
already changed twice — #136, #159).

The shim bridges only the **input** shapes, because the two harnesses' tool
vocabularies differ:

- **`Bash`** — identical payload (`tool_input.command`); passed straight to
  `decide()`.
- **`apply_patch`** (Codex's edit tool) — the payload carries the *patch
  string* in `tool_input.command`, not a `file_path`, but `decide()` keys the
  main-read-only and claimed-file checks on `file_path`. The shim parses target
  paths from the V4A `*** Add|Update|Delete File:` / `*** Move to:` headers,
  **absolutises them against the payload `cwd`** (else `decide()`'s
  `realpath`-based branch lookup binds to the hook process cwd, not Codex's),
  and synthesises one `Edit` payload per file. An unparseable patch still yields
  one cwd-anchored sentinel so the `main` guard fires (fail toward checking on
  the highest-value rule).

**Output needs no translation:** `decide()`'s deny dict already matches Codex's
`permissionDecision:"deny"` schema. The shim, like `hook_check.py`, **fails
open** (any error → allow) — this is a coordination guardrail, not a security
boundary.

Codex wires it from `~/.codex/config.toml` (or managed `requirements.toml` for
enforced org-wide install) with `matcher = "^(Bash|apply_patch)$"` pointing
`command_windows` at the shim. No logic lives on the Codex side; the shim ships
in-repo beside `hook_check.py`, so the two stay version-locked.

## Consequences

### Positive consequences

- `claims.json` + read-only-`main` now *bind* Codex's repo writes, not just
  advise them — enforcement parity with Claude, from one rule engine.
- Any future change to `decide()` covers both harnesses automatically; no
  second implementation to keep in sync.
- The shim carries a runnable `--selftest` (patch-path parsing, Bash
  passthrough, tool routing, deny-first / warn-drop verdict logic) with no
  framework or fixtures.

### Negative consequences

- **Warns are dropped on the Codex side** (`ponytail:` comment in the file): a
  claimed-file *warn* (non-blocking in Claude too) becomes a silent allow,
  because Codex's handling of Claude's `additionalContext` field is unconfirmed.
  Hard denies (main / cross-session branch) are always emitted. The
  read-before-work handoff ritual covers claimed-file coordination meanwhile;
  upgrade to `additionalContext` passthrough if Codex documents it.
- Codex's hooks do not cover hosted tools (e.g. Web Search) — repo writes go
  through `Bash`/`apply_patch`, which are covered, so this is not a gap for the
  invariant.
- Correct enforcement depends on Codex having claimed its branch via
  `coord_cli.py` and passing a stable `session_id` (present in Codex's payload);
  a stranger session id degrades to the main-guard only, which is the
  safe direction.

## Alternatives considered

- **Guardian LLM policy only** (`guardian_policy_config`): deterministic for the
  static read-only-`main` rule, but an LLM auto-reviewer can't reliably judge
  the *dynamic* claimed-file state in `claims.json`. Kept as the content/secret-
  scope layer; the shim adds the deterministic claims enforcement.
- **PowerShell reimplementation of the rules** (Codex's initial offer): rejected
  — a second copy of the decision logic drifts from `decide()`, recreating the
  "two fighting systems" the collaboration protocol explicitly avoids.
- **Invoke `hook_check.py` directly from Codex**: fails — its `Edit` branch
  needs a `file_path`, which Codex's `apply_patch` payload does not provide; the
  path must be reconstructed from the patch first.

## Related decisions

- Coordination framework + read-only-`main` invariant (CLAUDE.md > Worktrees &
  session coordination); prior fixes #136 (target-based branch resolution),
  #159 (file_glob claim preservation on resync).
- Claude↔Codex collaboration protocol (Mnemoverse domain `collab:autogis`).
