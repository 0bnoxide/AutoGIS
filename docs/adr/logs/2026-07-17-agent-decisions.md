# Agent decisions — 2026-07-17

## Duplicate CAD-export implementation from a cross-session collision — dropped my branch's version

**Decision:** During a routine open-issues sweep on branch
`claude/sleepy-wozniak-m5492g`, I implemented the arcpy `ExportCAD` wiring
for `BuildCADExportPackage` (issue #166, tool 8.9), wrote it up as
`docs/adr/0088-cad-export-arcpy-wiring.md`, committed (`81e3cb8`), and
pushed. Before opening a PR, comparing the branch against `origin/main`
turned up that a **separate, concurrent session** had independently
implemented the same fix — merged as PR #246 (`0bnoxide/salvage/cad-export-8.9`,
commits `ef0a96b`/`0c6817f`/`913ae16`), landed on `main` within minutes of my
own push, and also self-numbered its ADR **0088**
(`docs/adr/0088-civil3d-cad-export-arcpy-legs.md`) — a real numbering
collision, not just a duplicate-effort one.

The two implementations chose **opposite architectures** for the same
problem: mine wired the arcpy call CLI-first (no `.pyt` entry, per ADR-0039's
generation-2-tools precedent); the merged version added a `.pyt`
`BuildCADExportPackage` class and kept the CLI as a guard-and-redirect stub
(the older ADR-0006 Tools-2-8 pattern). The merged version also shipped a
points-only LandXML export for `export-civil3d --landxml` (reusing the
`export-survey-cad` CgPoints writer, ADR-0071) that my branch didn't attempt.
Both versions left the same two things undone: the CAD-layer *rename* piece
(`ExportCAD` has no per-input layer-rename parameter — an Esri limitation,
not an oversight) and the full contour/TIN LandXML surface leg (no native
arcpy tool exports that direction).

Since main's version was already reviewed (a follow-up review-fix commit,
`0c6817f`) and merged, and `git merge-tree` showed 14 real content conflicts
across the shared files, I reset `claude/sleepy-wozniak-m5492g` to
`origin/main` (`git reset --hard`, force-push) rather than opening a PR that
would ask a human to arbitrate two already-shipped solutions to the same
problem. Corrected my earlier GitHub comments on #238 and #166 (posted
before I saw main had moved) to reflect the real, current state.

**Reasoning:** A PR mixing two independently-merged fixes for the same issue
produces conflict-resolution work with no product value — main already has a
working, reviewed answer. The user's standing instruction is to defer to
already-completed work rather than layering redundant implementations; "open
a draft PR for review" was given before this collision was visible, and
re-confirmed by the user (with the added standing instruction that *future*
routine-run changes should always get a draft PR) once the collision was
explained. No PR was opened for the dropped commit — there was nothing left
in it that main didn't already have, generally in a more complete form.

**Root cause, concretely:** `docs/adr/README.md`'s own "Collision-prone case"
section already documents the fix for exactly this scenario — use an
`XXXX-kebab-case-title.md` placeholder filename instead of guessing the next
real ADR number when a branch might land alongside others, and assign the
real number at merge time. I didn't check that section before numbering my
ADR `0088`; had I used the placeholder, the number collision specifically
would have been avoided (the architecture/duplicate-effort collision itself
still would have happened — two sessions independently picking up the same
open issue is a coordination gap this repo's local session-coordination
registry, `.claude/coordination/claims.json`, doesn't reach, since it's
scoped to one main worktree and these were two separate cloud sessions on
independent branches with no shared registry).

**Revisit if:** this class of collision recurs. Options worth considering at
that point: (a) always use the `XXXX-` ADR placeholder as a matter of habit
regardless of perceived collision risk, since the cost of doing so is zero
and the benefit is exactly this; (b) have routine/autonomous sweeps check
for other open branches/recent PRs touching the same issue number before
starting implementation work, not just before opening a PR; (c) a
lighter-weight cross-session claim signal for issue-level work (e.g., a
"claiming this" comment on the GitHub issue itself before starting), since
GitHub issues are the one piece of state genuinely shared across independent
cloud sessions, unlike the local coordination registry.
