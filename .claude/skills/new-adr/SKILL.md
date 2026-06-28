---
name: new-adr
description: Scaffold the next numbered ADR from docs/adr/TEMPLATE.md. Usage: /new-adr <short title>
disable-model-invocation: true
---

# new-adr

Create the next sequential ADR from the project template.

## Steps

1. List `docs/adr/NNNN-*.md` and find the highest 4-digit number. The new number
   is that + 1, zero-padded to 4 digits (e.g. `0021` → `0022`). Only the
   `NNNN-`-prefixed files count toward numbering — ignore the dated legacy
   filenames (`2026-06-18-*.md`) and `README.md` / `TEMPLATE.md`.

2. Slugify the title from the argument: lowercase, spaces → hyphens, strip
   punctuation. New path: `docs/adr/<NNNN>-<slug>.md`.

3. Copy `docs/adr/TEMPLATE.md` into the new file, then fill in only:
   - the heading `# ADR-<NNNN>: <Title>` (human-readable title from the argument)
   - `**Status:** Proposed`
   - `**Date:** <today, YYYY-MM-DD>`

   Leave Context / Decision / Consequences / Alternatives as the template
   placeholders — those are the author's to write.

4. Add the index line to `docs/adr/README.md` if it keeps a list (match the
   existing format).

5. Report the new file path. Do **not** invent the decision content.
