# Agent decisions — 2026-08-01

## Keep the three requested value-add items in one batch ADR

**Decision:** Record #418, report-package verification, and the dashboard JSON
bridge in one proposed ADR while keeping their core implementations separate.

**Reasoning:** The owner explicitly selected all three as one value-add batch.
They share one narrow purpose—turning already-produced artifacts into reliable
handoffs—without sharing a new framework or dependency.

**Revisit if:** Either feature needs an independent release cadence or review
finds coupling outside the shared CLI/runtime/documentation surfaces.

## Treat unmanifested report-package files as policy-controlled warnings

**Decision:** Integrity mismatches and unsafe paths are errors; extra files are
warnings governed by the existing `--fail-on` option.

**Reasoning:** A hash mismatch or path escape disproves the manifest.  An extra
operator note does not alter a declared file, but strict delivery workflows can
still make it blocking with `--fail-on warning`.

**Revisit if:** A delivery contract requires every package to be a closed-world
inventory with no operator-added files.

## Reuse Tool 6.7's in-memory mart rows

**Decision:** Add optional JSON output to `build-dashboard-data-mart` instead of
creating a standalone GDB-to-JSON command.

**Reasoning:** Tool 6.7 already materializes the exact ten row lists consumed by
`agol refresh-dashboard`; rereading the GDB would duplicate ArcPy access and
schema mapping.

**Revisit if:** A demonstrated workflow needs JSON export from an existing GDB
without rebuilding the mart.

## Keep adjacent defects out of the requested implementation

**Decision:** File #424–#429.  Absorb the generated metadata-name collision
into #418 and the package path-safety blocker in #429 into this integrity
batch; leave #424–#428 out of this branch.

**Reasoning:** The metadata-name collision is the same destination-injectivity
root cause as #418.  Redirected writes and unmanifested streams would make the
new verifier claim unsafe packages are clean, so they block this batch.
Empty/unsafe dashboard refresh, FileGDB directory copying, unknown roles, and
stale ADR reservation remain distinct contracts requiring separate review.

**Revisit if:** The owner explicitly expands this branch or a finding blocks
the requested producer/verifier bridge.

## Keep package-command reports outside the artifact under test

**Decision:** Reject `build-report-package --report` and
`verify-report-package --report` paths that resolve inside the package, share
file identity with any package file, or name an alternate data stream.  This
covers symlink, junction, hard-link, and ADS aliases.

**Reasoning:** Writing the QA report after verification could otherwise replace
`manifest.csv` or a delivered file while the command still exits from its stale
in-memory PASS result.

**Revisit if:** Reporting becomes transactional and the report itself is added
to a separately authenticated package inventory.

## Treat filesystem aliases as part of package identity

**Decision:** Reject lexical parent segments in the output path, DOS 8.3
short-name forms, named streams on sources or packaged files/directories,
reparse-point entries, and multi-linked destination or package files.

**Reasoning:** Normalized path strings and SHA-256 alone do not expose Windows
short-name aliases, junctions, NTFS alternate streams, or hard links.  Each can
redirect writes or hide content outside the manifest while preserving an
apparently clean path.

**Revisit if:** Packaging moves to a format whose writer defines and enforces a
closed archive namespace independent of host filesystem aliases.
