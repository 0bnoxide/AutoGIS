---
name: new-adr
description: Scaffold the next numbered ADR from docs/adr/TEMPLATE.md. Usage: /new-adr <short title>
disable-model-invocation: true
---

# new-adr

Create the next sequential ADR from the project template.

## Steps

1. Get the next number from the preflight — it checks local ADRs **and** open
   PRs, so concurrent sessions collide less often (the recurring `0099 → 0105`
   renumber is what this targets):

   ```bash
   python .claude/skills/new-adr/next_adr_number.py   # prints e.g. 0107
   ```

   Only `NNNN-`-prefixed files count; dated legacy names (`2026-06-18-*.md`),
   `README.md`, and `TEMPLATE.md` are ignored. It **reduces, not eliminates**
   collisions — two sessions that both grab a number *before either opens a PR*
   are invisible to the PR scan, so still sanity-check against origin/main +
   open PRs if two sessions are active. If `gh` is offline/unauthed it degrades
   to a local-only scan (still correct, just less protective).

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
