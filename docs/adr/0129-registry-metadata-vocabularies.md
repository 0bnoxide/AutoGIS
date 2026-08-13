# ADR-0129: Registry metadata vocabularies — roadmap ids come from the catalog, runtime from the enum

**Status:** Accepted

**Date:** 2026-08-13

## Context

ADR-0127 recorded #458 (six shipped tools carrying a `roadmap_id` the catalog
assigns to a different tool) as *deliberately not fixed* — "the right number is
an owner call". PR #475 subsequently resolved it autonomously, and merged on the
owner's instruction; the retroactive `pr-reviewer` pass (posted to #475)
confirmed every reassignment but flagged that the decision had only an
agent-decision log behind it. Per CLAUDE.md, a log supplements an ADR — this is
the missing ADR.

## Decision

Two vocabulary invariants, both established by PR #475 and pinned by
`tests/test_tool_registry_parity.py`:

1. **`roadmap_id` may hold only a number the catalog assigns to that tool.**
   `docs/envmon-feature-roadmap.md` is the authority; each section's
   `**Tool name:**` line names the owner. A post-roadmap extra carries `""`,
   not a borrowed number. What looked like an owner call in ADR-0127 turned
   out to be derivable: none of the seven extras appears anywhere in the
   catalog, and the README's independent `Roadmap #` column agreed with the
   catalog in every reassigned case. The numbers went back to their catalog
   owners (see the table in PR #475's description).

2. **`ToolCapability.runtime` may hold only a `Runtime` enum name**
   (`RUNTIME_CLASSES`: CLOUD, HYBRID, LOCAL). Draft-ness lives in `status`
   alone. `DRAFT` was removed from the one row holding it (#468) and from
   `--runtime`'s `click.Choice`, which now derives from `RUNTIME_CLASSES` —
   a **breaking change**: `list-tools --runtime DRAFT` exits non-zero; scripts
   use `--status draft`. The 2026-06-28 ListAvailableEnvTools spec carries an
   amendment note.

## Consequences

- `roadmap_id` stays display-only (single consumer: the verbose listing).
- Follow-ups from the retroactive review: #481 (test anchors `docs/` on the
  installed package), #482 (sibling test still whitelisted `DRAFT`),
  #483 (core docstrings still cited "Tool 7.5"), #484 (test docstrings ditto)
  — fixed in the PR that adds this ADR.
- Still open: #476 (catalog's own duplicate 8.2/8.3/8.4 headings) and
  #477 (thirteen tools with a README `Roadmap #` but empty `roadmap_id`).
