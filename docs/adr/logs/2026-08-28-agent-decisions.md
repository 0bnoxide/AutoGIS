# Agent decisions — 2026-08-28

Session: owner asked for "a couple or a few issues that pair well, for a fix",
then for the PR to be carried to merge. Branch
`claude/issue-pairing-fixes-igfjdh`, PR #516. The design decision for #450 is in
**ADR-0135**; this log records the autonomous judgment calls that ADR does not,
per `docs/adr/logs/README.md`.

## Scope calls

**Paired #512 with #450.** Both are the same shape — a shared `core/` seam that
misrepresents its own state to callers — and both are arcpy-free, so both are
fully verifiable headless. No file overlap between the two fixes.

**Skipped #449 despite it being the obvious third.** It is the nearest neighbour
of #450 (inert analyte-dictionary keys, same survey, same "wire it or withdraw
it" shape), but its own follow-up comment scopes the wire-vs-delete call to the
owner as a product decision. #450's equivalent call was reopened by the owner's
instruction this session; #449's was not, and one instruction does not
generalize to the other issue.

**Skipped the owner-gated QA batches** (#195, #231, #238, #272, #307, #312,
#498, #504) — they need a human at an ArcGIS Pro or AGOL console. #388 (slow
Windows CI), #414, #465 and the #349 housekeeping audit were ranked below the
pair and left.

## Judgment calls inside the fixes

**#450 — acted on a decision the 2026-08-08 session deferred to the owner.**
That log recorded "deleting shipped config keys or relaxing load validation is
an owner call, not a bug fix. Left open, reported." The owner directing this
session to pick open issues and fix them is what resolves that, and nothing
else — so the substance went into ADR-0135 rather than riding in as a silent
bug fix inside a PR body. The deferral was correct when it was made; recording
the reversal is what keeps it correct now.

**#450 — flagged the `validate-config` consequence, and was wrong to stop
there.** Narrowing `SITE_REQUIRED` also stopped `envmon validate-config`
reporting those nine keys, since both read one constant. I named it in the ADR
and PR body as an owner follow-up rather than fixing it, reasoning that adding
a second list was a mechanism invented to soften a consequence the owner might
want. The cold `pr-reviewer` rejected that and was right: it demonstrated a
scaffold with `_TODO` lines deleted going from 7 errors/exit 1 to
`0 error(s) / PASS / exit 0`, and pointed out that `coordinate_system` *is*
consumed, with its only other signal living on an arcpy-only path a headless
operator never reaches. A silent regression in an operator-facing validator is
not a preference to be offered — flagging a defect is not the same as leaving
one in. Fixed with `SITE_RECOMMENDED` at WARNING (ADR-0135 §1a), plus the
`validate_site` test whose absence let the suite stay green through it.

**#450 — `record_result` appends rather than raises.** Raising would break the
class's only existing caller (`tests/test_reporting.py`) to protect a caller
that does not exist yet. Appending removes the silent-data-loss path the
docstring invited, which was the reported defect.

**#512 — widened the guard after the first fix passed its own test.** The
initial commit wrapped only the `PRAGMA` call, and the review probe found the
identical defect still reachable one call earlier: `sqlite3.connect()` is lazy
for a non-SQLite file but raises immediately for an existing-but-unopenable
path (a directory). The CLI is shielded there by `click.Path(dir_okay=False)`,
so the CLI-level repro in the issue could not expose it — only a direct call to
the core function does. Fixed at the seam all callers route through rather than
at the seam the issue happened to name.

**#512 — kept the broad `sqlite3.DatabaseError` catch.** It also catches
`OperationalError`, so a locked or I/O-failing database now reports
`db_unreadable` with a slightly generic message. A QA error with an imprecise
cause beats an unhandled traceback, and the exit code and report shape are
unchanged either way.
