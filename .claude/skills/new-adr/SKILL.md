---
name: new-adr
description: Scaffold the next numbered ADR from docs/adr/TEMPLATE.md. Usage: /new-adr <short title>
disable-model-invocation: true
---

# new-adr

Create the next sequential ADR from the project template.

## Steps

1. Allocate the ADR before creating it. For a coordinated, verified session,
   reserve the number with the strict scan:

   ```powershell
   python .claude/coordination/coord_cli.py reserve-adr --strict --session $env:AUTOGIS_SESSION_ID
   ```

   A successful command authorizes the printed numeric filename. If session
   resolution or the strict GitHub scan fails, create
   `docs/adr/XXXX-<slug>.md` instead; never use a fail-soft numeric suggestion.
   The no-argument allocator is informational only and never authorizes a
   numeric filename:

   ```powershell
   python .claude/skills/new-adr/next_adr_number.py
   ```

2. Slugify the title from the argument: lowercase, spaces → hyphens, strip
   punctuation. The new path is the authorized numeric
   `docs/adr/<NNNN>-<slug>.md`, or the fallback `docs/adr/XXXX-<slug>.md`.

3. Copy `docs/adr/TEMPLATE.md` into the new file, then fill in only:
   - the heading `# ADR-<NNNN>: <Title>` or `# ADR-XXXX: <Title>`
     (human-readable title from the argument)
   - `**Status:** Proposed`
   - `**Date:** <today, YYYY-MM-DD>`

   Leave Context / Decision / Consequences / Alternatives as the template
   placeholders — those are the author's to write.

4. Add the index line to `docs/adr/README.md`. A placeholder has exactly one
   `[XXXX](XXXX-<slug>.md)` row.

5. A draft PR may retain `XXXX`; a ready PR and `main` may not. Before making
   the PR ready, finalize every placeholder:

   ```powershell
   python .claude/skills/new-adr/next_adr_number.py --finalize
   ```

   Review the printed mapping, stage and commit normally, then release the ADR
   reservation after merge. `adr-policy` is the fail-closed required merge gate
   for human, remote, and fork PRs. Report the new file path; do **not** invent
   the decision content.
