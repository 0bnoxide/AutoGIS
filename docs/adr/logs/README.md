# Agent-decision logs

This directory holds **daily agent-decision logs** — a running audit of the
*autonomous judgment calls* an agent made **without direct human oversight**
during a session ("use best judgment and log those decisions accordingly").
The purpose is historical auditing of the agent's "free will": what was chosen,
what was rejected, and why.

## File convention

- One file per day: `YYYY-MM-DD-agent-decisions.md`.
- Append one section per decision. Record **Decision**, **Reasoning**, and a
  **Revisit if** trigger. Keep it factual and specific.
- These logs live **here only** (`docs/adr/logs/`). Do not start a parallel
  location (a former `docs/decisions/` path fragmented the record and was
  consolidated back here — see ADR-0007).

## A log is NOT a substitute for an ADR

This is the distinction that gets missed:

| | Purpose | Home |
|---|---|---|
| **ADR** (`docs/adr/NNNN-*.md`) | The **architectural decision record** — the durable "regular logging" of a design/structure/invariant/batch decision. | `docs/adr/` |
| **Agent-decision log** (this dir) | A **supplementary audit** of the agent's autonomous judgment calls. | `docs/adr/logs/` |

A batch of tools or any architectural decision still needs an **ADR**
(see [`../README.md`](../README.md) for format + the `/new-adr` skill). Logging
the judgment calls here does **not** discharge that. When both exist for the same
work, the ADR summarises the decision and cross-references the day's log for the
per-decision detail (see ADR-0030 / ADR-0031 for the pattern).

## Related
- [ADR-0007: migrate project logs to ADR format](../0007-logs-to-adr-migration.md)
- [ADR index](../README.md)
