# AutoGIS — Codex session guide

Read and follow [`CLAUDE.md`](CLAUDE.md) as the canonical repository guide for
architecture, invariants, validation, and coordination. Claude-specific command
names do not rename repository paths; use the equivalent Codex tool where needed.

## Default working mode — ponytail

Every Codex session must invoke the `ponytail` skill (full) before writing or
reviewing code and keep it active for the session. The skill is vendored at
`.agents/skills/ponytail/SKILL.md`; companion skills live beside it. The shared
`.claude/scripts/sync-ponytail-skills.sh` mirror keeps the Codex and Claude Code
copies byte-identical to the locally installed plugin.

Without the ponytail plugin installed, the vendored skills load unnamespaced:
invoke them as `$ponytail`, `$ponytail-review`, `$ponytail-help`, etc. The
vendored `ponytail-help` card's `$ponytail:<skill>` forms apply only when the
plugin itself is installed; that text is upstream's and stays unpatched here so
the mirror check stays clean.
