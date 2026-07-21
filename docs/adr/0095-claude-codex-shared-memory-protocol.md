# ADR-0095: Claude↔Codex correspondence protocol over shared memory (`collab:autogis`)

**Status:** Accepted

**Date:** 2026-07-21

## Context

Claude Code and Codex collaborate on this repo from the same machine but
different harnesses. File/branch *locking* is handled by the coordination
framework's `hook_check.decide()` — binding Claude natively and Codex via the
shim (ADR-0094). **Parity is conditional, not absolute** (see Consequences
and #270): the shim binds Codex only while the file exists at the absolute
path wired in `~/.codex/config.toml`. What locking does not carry is *context* —
handoffs, in-flight uncommitted state, durable decisions, blockers.

Both agents share one Mnemoverse account (confirmed empirically 2026-07-20:
each reads the other's writes), so the memory domain **`collab:autogis`** is
the shared channel. An initial protocol was agreed *inside* the channel
itself, which surfaced three defects:

1. **Bootstrap problem.** The protocol was only discoverable by an agent that
   already knew to read `collab:autogis`. Nothing in the repo mentioned the
   channel, so every fresh session depended on the user manually re-briefing
   it — backwards, given "repo is source of truth."
2. **No routing rule.** "Pointers not payloads" was not sharp enough to stop
   the channel from mirroring GitHub PR threads — the worst outcome for a
   relevance-ranked store, where stale mirrors outrank fresh messages.
3. **Mechanical defects.** "Delete superseded messages once acknowledged"
   depends on an ack signal that does not exist between sessions; and
   Mnemoverse's importance gate can silently *filter* a terse write (a
   protocol-confirmation message scored 0.31 — barely stored), so a
   one-line handoff can vanish while its writer believes it is on record.

A design constraint that shapes everything: **Mnemoverse is a semantic top-k
store, not an ordered mailbox.** `memory_read` returns relevance-ranked
matches, not "everything since last check"; old entries never expire and can
outrank new ones.

## Decision

This ADR is the canonical protocol text; the channel holds only live
messages. CLAUDE.md (canonical for Codex too, per AGENTS.md) points here.

### Channel and authority

- Channel = Mnemoverse domain `collab:autogis`. **Context only.** GitHub and
  the repo remain source of truth; `hook_check.decide()` (+ ADR-0094 shim)
  remains the sole locking authority. The channel never locks anything.
- Standing user permission for both agents to read/write this domain is on
  record (channel message, 2026-07-20). Security exclusions: no credentials,
  API keys, env values, customer data, private source, raw diffs, or logs.

### Message types (exactly three)

Every message starts with a literal type token plus a header
`[FROM <tool> → <tool>, YYYY-MM-DD]`, and is self-contained:

- **`[STATUS]`** — handoff: branch, what changed, next owner, requested
  action, and `SUPERSEDES <date>` naming the writer's prior status.
- **`[DECISION]`** — durable coordination call; must point at an ADR or
  issue once one exists.
- **`[BLOCKER]`** — needs the other agent; cleared by an explicit reply.

Literal tokens make retrieval deterministic — session-start queries key on
them, where free prose is what semantic search loses.

### Routing rule (what goes where)

**If the work has a GitHub artifact (PR/issue), status updates go on that
artifact — not the channel.** Both agents already read GitHub, and that is
where reviewers look. A channel `[STATUS]` covers only the **pre-artifact
gap**: uncommitted work, un-pushed branches, "stopping halfway through X."
Messages carry pointers (`see PR #NNN`), never payloads.

### Write mechanics

- **Self-service supersession:** when writing `[STATUS]` N+1, the writer
  deletes their own `[STATUS]` N in the same sitting (`memory_delete`). No
  ack is required or waited for — acks exist only for `[BLOCKER]`s. Never
  delete the other agent's messages (downrank via `memory_feedback` at most).
- **Lifecycle deletion (codex amendment, 2026-07-21):** a successor message
  is not the only terminator. Delete your own pre-artifact `[STATUS]` when
  the GitHub artifact is created, or the work completes or is abandoned —
  otherwise the routing rule guarantees the last pre-artifact status goes
  stale forever (status moves to GitHub, so no successor ever supersedes
  it). Likewise the `[BLOCKER]` originator deletes their own blocker after
  verified resolution or escalation to a GitHub issue.
- **Check the write result.** If the importance gate reports *filtered*,
  enrich the message and rewrite — a filtered handoff is a silent drop.
- **Low volume is a feature.** Write on ownership change, decision, or
  blocker only — never per-commit narration. Every extra entry dilutes
  top-k precision for both agents.
- Concept-tag artifact identities (`pr-267`, `adr-0095`) plus `autogis` and
  the type token, so association learning links threads.

### Read ritual

At the start of any AutoGIS session (when Mnemoverse tools are present), run
**three** reads against `collab:autogis` — querying `STATUS handoff`,
`BLOCKER`, and `DECISION` — before taking over shared work (codex amendment,
2026-07-21: a ritual that skips `DECISION` would miss pending cross-agent
decisions like the very negotiation that produced this ADR). One targeted
read per message type covers semantic-search misses; one broad query does
not. Volume is deliberately low, so the third read costs nothing.

## Consequences

### Positive consequences

- The protocol is discoverable from the repo alone: a fresh session of either
  agent finds it via CLAUDE.md/AGENTS.md without user re-briefing.
- The routing rule keeps the channel small and high-precision, confined to
  the one job GitHub cannot do (pre-artifact context).
- Supersession no longer depends on a nonexistent ack; filtered-write checks
  close the silent-drop hole.

### Negative consequences

- Discipline-bound, not enforced: no hook can verify either agent performed
  the read ritual or the supersession delete. Acceptable — the channel is a
  context aid; everything binding lives in GitHub and the coordination hook.
- **ADR-0094 parity is conditional until #270 closes** (codex amendment,
  2026-07-21, evidence verified by both agents): `~/.codex/config.toml`
  wires the hook to an absolute path inside the primary checkout; with that
  checkout on a pre-#268 branch the shim file is absent and a live Codex
  `apply_patch` probe in a main worktree was **silently allowed** — not the
  block-all previously assumed for a missing shim (hook spawn-failure ≠
  script exit 2). Until a current-harness main-write probe is denied and
  enforcement survives old-branch checkouts, treat Codex-side locking as
  best-effort and lean on the read ritual + read-only-`main` discipline.
- Channel history is not versioned or auditable the way the repo is; durable
  decisions must therefore land as ADRs, with the channel entry pointing at
  them (as this one does).
- If in practice the channel degrades into mirroring PR threads anyway, the
  correct response is to shrink its role toward `[BLOCKER]`-only — revisit
  then, not preemptively.

## Alternatives considered

- **A status file in the repo** (`docs/collab/STATUS.md`): versioned and
  hook-enforceable, but useless for exactly the pre-artifact gap the channel
  exists for (un-pushed/uncommitted state isn't in the repo yet), and it
  pollutes history with coordination chatter.
- **A Mnemoverse room + invite:** unnecessary — both agents share one
  account/namespace, proven by reading each other's messages.
- **Richer message taxonomy** (per-tool inboxes, threading conventions):
  rejected as speculative; three types cover observed traffic. Revisit if a
  real message doesn't fit.

## Related decisions

- ADR-0094 — Codex coordination shim (locking symmetry; this ADR handles the
  context layer above it).
- ADR-0087 — production roadmap (the work being coordinated).
- CLAUDE.md > Worktrees & session coordination (locking framework).
