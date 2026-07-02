# docs/ index

This directory accretes per development batch. This index orients a reader to
where things live; it does not replace reading the files themselves.

## Durable, authoritative

- **[`adr/`](adr/README.md)** — Architecture Decision Records. The durable record of
  every architectural/structural/invariant/tool-batch decision. Start here for
  "why is it built this way".
- **[`adr/logs/`](adr/logs/README.md)** — dated agent-decision logs, a supplement to
  ADRs (autonomous judgment-call audit trail), not a substitute for one.
- **`../CLAUDE.md`** (repo root) — the canonical session/project guide: layout,
  invariants, worktree/coordination protocol, deferred roadmap groups.
- **[`new-envmon-tool-checklist.md`](new-envmon-tool-checklist.md)** — blessed
  helpers to reuse before writing a new envmon tool. Not dated/point-in-time;
  kept current, enforced by `envmon-spec-checker`.

## Design history, per feature

- **`superpowers/specs/YYYY-MM-DD-<topic>-design.md`** — brainstormed design docs,
  one per feature/tool, dated. Point-in-time design rationale; superseded by the
  matching ADR if the two ever disagree.
- **`superpowers/plans/YYYY-MM-DD-<feature-name>.md`** — the bite-sized implementation
  plan that shipped each spec.

## Independent reviews

- **`reviews/`** — independent architecture reviews (e.g.
  `fable-architecture-review.md`, source of the H/M/L findings tracked as GitHub
  issues). Point-in-time snapshot at the review date; check the linked issues for
  current status.

## Not yet gated

- **`candidates/`** — roadmap candidates and their evaluation framework/results,
  not yet phase-gated into active work. See CLAUDE.md's "Deferred tool groups"
  section for which groups are explicitly blocked pending a gate decision.

## Flat top-level files

The remaining top-level `docs/*.md` files (roadmap snapshots, ROI analyses, status
updates, integration notes) are point-in-time working documents from specific
batches -- not kept current after the fact. Treat a date in the filename or a
"Status: as of <date>" line as the file's shelf life; for current status, prefer
`git log`, the ADR index, or asking in-session rather than trusting an undated
roadmap file. No archive convention exists yet for these; consult a file's own
date before relying on it.
