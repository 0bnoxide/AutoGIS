# ADR Number Allocation Enforcement — Design

**Date:** 2026-08-13

**Status:** Approved by the owner on 2026-08-13

**Tracks:** issue #492 and the collision history recorded by ADR-0110

**Scope chosen by user:** enforcement for every pull request, including
manual, remote, and fork-authored PRs—not only locally coordinated agent
sessions.

## Incident status

Issue #492 was raised when concurrent PRs #487 and #488 each added a different
`docs/adr/0129-*.md` file. The immediate collision has since been resolved:
PR #487 merged ADR-0129, PR #488 was renumbered to ADR-0130 before merge, and
issue #492 is closed. That manual recovery fixed the two branches but did not
make the invariant enforceable for future PRs. This design is the systemic
follow-up.

## Problem

AutoGIS currently has four partial defenses against ADR-number collisions:

1. `docs/adr/README.md` tells parallel branches to use an `XXXX-`
   placeholder.
2. `.claude/skills/new-adr/next_adr_number.py` scans merged ADRs and open PR
   file lists before suggesting the next number.
3. `coord reserve-adr` can atomically reserve a number in the local shared
   coordination registry.
4. `tests/test_adr_numbering.py` rejects duplicate numeric prefixes once both
   files exist in one checkout.

None is a complete gate:

- The placeholder rule is documentation only.
- The open-PR scan deliberately fails soft and can return a locally derived
  number when GitHub is unavailable.
- `reserve-adr` is optional and covers only sessions sharing this machine's
  registry.
- The merged-tree test cannot see a different open PR. Each colliding PR can
  therefore be green independently.
- ADR-0110 selected reservations over placeholders, while the current README
  prescribes placeholders for parallel work. Authors receive contradictory
  policy.
- The active `RulesForThee` repository ruleset requires a pull request and
  resolved review threads, but it currently requires no status check. A new CI
  check would remain advisory unless the ruleset also changes.

The root cause is not number parsing. It is the absence of one fail-closed,
GitHub-wide merge gate backed by a consistent authoring policy.

## Goals

- Prevent two different ADR files with the same numeric prefix from both
  satisfying the merge gate.
- Cover every PR regardless of which editor, agent, machine, or fork created
  it.
- Preserve the existing sequential four-digit ADR convention.
- Keep local authoring useful when GitHub or the coordination registry is
  unavailable without allowing an unverified guess to masquerade as safe.
- Reuse the existing allocator, registry, hook, and CI workflow.
- Produce exact diagnostics naming the conflicting files and PRs.
- Keep the policy implementation stdlib-only and arcpy-free.

## Non-goals

- No bot pushes, merge queue, or privileged `pull_request_target` workflow.
- No renumbering of historical ADRs.
- No replacement of sequential IDs with PR numbers, timestamps, or UUIDs.
- No guarantee that a red external branch can never temporarily contain a
  duplicate number. The enforceable contract is that a collision cannot pass
  the required check or merge.
- No requirement to make unrelated test or analysis jobs load-bearing; the
  only merge-policy change is requiring the ADR policy check.
- No new dependency or product-code change.

## Decision

Use three layers, with GitHub CI as the authority:

1. **Reservation-first local authoring.** A coordinated session must reserve a
   number before committing a new numeric ADR. If it cannot prove both a live
   local reservation and a complete open-PR scan, it drafts `XXXX-<slug>.md`
   instead of guessing.
2. **A required, fail-closed PR policy check.** A dedicated `adr-policy` job
   compares the PR against its base branch and every open PR. It rejects
   collisions and unfinalized placeholders on ready PRs.
3. **Strict placeholder finalization.** The existing ADR-number owner script
   gains a finalization mode that refreshes authoritative state, allocates the
   next free number, and updates the filename, H1, and README index together.

The existing merged-tree tests remain the last local invariant. ADR-0110 is
amended rather than creating another ADR for this correction.

## State model

An added ADR is in one of two states:

```
XXXX-<slug>.md  --strict finalization-->  NNNN-<slug>.md
    draft                                   finalized
```

- A draft PR may contain `XXXX-*.md`.
- A draft PR may also contain a numeric ADR when a coordinated session already
  obtained a valid reservation; it must still be collision-free.
- A ready-for-review PR may not contain an added `XXXX-*.md`.
- `main` may never contain `XXXX-*.md`.
- A numeric ADR is mergeable only when its prefix is unique in its own tree,
  absent from the base under a different path, and absent from every other open
  PR under a different path.
- Editing the same existing ADR path is not a new number claim. Ordinary Git
  conflict handling remains responsible for concurrent content edits.

## Component 1 — authoring and local coordination

The existing `new-adr` skill remains the entry point. Its first step changes
from “pick a number, optionally reserve when concurrency seems likely” to:

1. Resolve the current coordination session.
2. Perform a strict scan of the base ADRs and all open PR file lists.
3. Atomically reserve the next number with `coord reserve-adr`.
4. Create the numeric ADR only if all three steps succeed.
5. Otherwise create `XXXX-<slug>.md` and report why allocation degraded.

The current fail-soft number query remains available for informational use, but
it is no longer sufficient authorization to create a real-numbered ADR.
Implementation should expose strict scan failure explicitly rather than asking
callers to parse warning text from stderr.

The PreToolUse commit path adds a local guard for newly added or renamed numeric
ADRs:

- Inspect the staged paths for `docs/adr/NNNN-*.md`.
- Ignore modifications to a tracked ADR at the same path.
- Require a live `kind=adr`, matching-number claim owned by the current
  session.
- Deny the commit with a command to reserve or rename to `XXXX` when the
  claim is absent.

This hook is an early mistake detector, not the cross-repository authority. It
may preserve the coordination framework's current fail-open ceiling on
unexpected internal errors because the required PR check independently catches
collisions from hooks, humans, alternate clients, and forks.

Reservations keep the existing heartbeat, TTL, and explicit release behavior.
Multiple ADRs in one branch require one reservation per number.

## Component 2 — GitHub-wide ADR policy check

Extend the existing ADR-number owner,
`.claude/skills/new-adr/next_adr_number.py`, rather than building a second
allocator. The tool gains a PR-check mode with pure functions for:

- recognizing real ADR filenames while excluding dated logs, README, TEMPLATE,
  and `docs/adr/logs/`;
- identifying ADR paths added or renamed by the current PR;
- collecting numbered ADR claims from the base branch;
- collecting numbered ADR claims and placeholder paths from every other open
  PR;
- validating placeholder state and numeric uniqueness; and
- rendering deterministic diagnostics.

The GitHub client must paginate both the open-PR list and each PR's changed-file
list. Removed files do not claim a number. The current PR is excluded from the
“other PR” set. A same-path edit is not treated as a number collision; two
different slugs with the same prefix are.

The check is fail-closed in CI:

- authentication, pagination, malformed response, timeout, or rate-limit
  failure makes the job fail;
- it never falls back to a local-only answer;
- diagnostics distinguish “policy violation” from “GitHub state could not be
  verified.”

Add a dedicated `adr-policy` job to `.github/workflows/ci.yml`. It runs
before the full test job needs to finish, uses read-only `contents` and
`pull-requests` permissions, and adds no dependency installation. The
`pull_request` trigger must explicitly retain `opened`, `synchronize`, and
`reopened` and add `ready_for_review` and `converted_to_draft`, so
placeholder validity is re-evaluated when PR state changes.

On a pull request the job enforces:

- no duplicate numeric prefix within the checked-out tree;
- no added numeric ADR colliding with a different base path;
- no added numeric ADR colliding with a different path in another open PR; and
- no added `XXXX-*.md` when the PR is ready for review.

On a push to `main` it enforces:

- no duplicate numeric prefix; and
- no `XXXX-*.md` at the ADR root.

External PRs do not need access to the local reservation registry. A manually
chosen but globally unique number may pass CI; a collision cannot. The local
reservation rule prevents the common agent race, while CI supplies the
universal guarantee.

## Component 3 — strict finalization

The existing ADR tool gains a `--finalize` operation for branches containing
one or more `XXXX-*.md` files.

Before writing, it must:

1. confirm it is not on `main`;
2. refresh or query the current base branch;
3. enumerate every open PR completely;
4. include live local reservations when available;
5. find every root-level `XXXX-*.md` in the branch;
6. allocate consecutive next-free numbers in deterministic slug order;
7. verify each file begins with the expected `# ADR-XXXX` H1;
8. locate exactly one matching README index entry per placeholder; and
9. validate the fully transformed in-memory result for unique prefixes and
   matching H1s.

Only after all preflight checks pass may it rename files and replace their H1
and README links. A validation failure performs no writes. An unexpected I/O
failure must restore the originals created or changed by that invocation before
returning nonzero.

The operation prints the old-to-new mapping and the exact files changed.
It does not commit, push, label, ready, or merge the PR.

## Component 4 — load-bearing repository ruleset

The active repository ruleset is `RulesForThee` (observed ID `18357662` on
2026-08-13) and targets the default branch. Its current pull-request rule has no
required status checks. Implementation must resolve the active ruleset by name
again before updating it rather than assuming the observed numeric ID is
permanent.

After the new job exists and has reported successfully on its implementation
PR, update that ruleset to require the `adr-policy` check. Keep the existing
pull-request and review-thread-resolution requirements and the empty bypass
list unchanged.

This settings change is part of the feature, not optional administration.
Without it, a red policy job can still be merged and the user-selected
“every PR” requirement is unmet.

The dedicated check is preferred over making the full `pytest` job required:
the issue concerns ADR allocation, and silently broadening the repository's
entire merge policy is outside scope.

## Diagnostics and error behavior

Messages must be actionable and stable enough for tests. Examples:

- `ADR 0132 is also added by PR #501 as docs/adr/0132-other.md; use XXXX or finalize after that claim changes.`
- `docs/adr/XXXX-new-policy.md is unfinalized; ready PRs require numeric ADR filenames.`
- `Open-PR ADR scan failed after page 2; allocation was not verified and no number was assigned.`
- `ADR 0133 is staged without this session owning reservation 0133; run coord reserve-adr or rename the file to XXXX-....md.`

Do not print tokens, response headers containing credentials, or full GitHub
payloads. Network failures should retain the HTTP status or exception class but
not sensitive request metadata.

## Testing

### Pure allocation and PR-policy tests

Cover:

- numeric ADRs, dated legacy names, templates, logs, and placeholders;
- one PR versus base, one PR versus another PR, and multiple collisions;
- same existing path edited by multiple PRs;
- removed ADR files;
- multiple ADRs within one PR;
- draft and ready placeholder behavior;
- pagination across both PR and file pages;
- malformed JSON, authentication failure, timeout, and partial-page failure;
- deterministic ordering of conflict diagnostics; and
- the historical #487/#488 shape: two distinct `0129-` slugs cannot both pass.

All network tests use injected responses or a fake client. Unit tests never call
GitHub.

### Coordination-hook tests

Cover:

- a staged numeric addition with the session's reservation is allowed;
- the same addition without a matching reservation is denied;
- another session's reservation is denied;
- `XXXX` additions are allowed;
- an edit to an existing numeric ADR is allowed;
- a rename to a new numeric prefix is checked; and
- staged-diff inspection failure retains the documented local fail-open
  behavior.

### Finalization tests

Use temporary repositories to cover:

- one placeholder;
- multiple placeholders allocated consecutively in stable order;
- H1 and README link replacement;
- stale base and open-PR collisions;
- missing or duplicate README entries;
- malformed H1;
- strict scan failure before writes;
- validation failure leaving the tree byte-identical; and
- simulated mid-write failure restoring originals.

### Workflow and live verification

- Parse the workflow and assert the `adr-policy` job and PR-state triggers are
  present.
- Run the focused ADR and coordination suite arcpy-free.
- Run the historical #487/#488 file list through the policy command and confirm
  a collision result.
- On the implementation PR, confirm the new check appears and passes.
- Add the required-check rule, then confirm the ruleset reports
  `adr-policy` as required with no bypass actor.
- Audit currently open PRs once before enabling the rule so an existing,
  unrelated PR is not surprised by an unknown collision.

## Documentation and decision records

- Amend ADR-0110 with the enforced policy: reservation-first locally,
  placeholder on degraded allocation, strict GitHub PR gate, and required
  ruleset check.
- Reconcile `docs/adr/README.md` with ADR-0110. The README should no longer
  present placeholders and reservations as competing policies.
- Update the `new-adr` skill with the automatic reservation/fallback and
  finalization commands.
- Keep `tests/test_adr_numbering.py` as the merged-tree invariant, extending
  it only where shared pure helpers improve consistency.
- Reference closed issue #492 and PRs #487/#488 as the incident evidence.

No new ADR is created: this design corrects and strengthens the existing
ADR-0110 tooling decision.

## Rollout

1. Land the policy code, tests, workflow job, skill text, README reconciliation,
   and ADR-0110 amendment in one PR.
2. Verify the new job on that PR and audit all currently open PR ADR claims.
3. Update `RulesForThee` to require `adr-policy`.
4. Confirm the implementation PR remains mergeable only while the check passes.
5. Merge the implementation PR.
6. Verify the required rule and push-to-main policy against the merged head.

If the ruleset cannot be updated, the PR must remain explicitly incomplete; the
repository code alone does not satisfy “every PR.”

## Alternatives considered

### CI collision scan without local reservation

Smaller, but leaves the common pre-PR race intact and throws away the shared
allocator already built for this exact problem. Rejected.

### Local reservation without a required PR check

Fast for coordinated sessions but invisible to humans, forks, other machines,
and clients without the hook. This is the current failure mode. Rejected.

### Placeholder-only PRs plus a serialized GitHub bot

Could prevent even temporary numeric overlap, but requires bot writes,
cross-fork permission handling, a concurrency protocol, recovery from partial
bot pushes, and a privileged workflow. The required check provides the merge
guarantee with much less machinery. Rejected.

### Use PR numbers, timestamps, or UUIDs as ADR IDs

Eliminates allocation but abandons the accepted sequential corpus and needs a
migration or mixed identifier grammar. Rejected.

### Require the full pytest job

Would make the ADR check load-bearing if embedded there, but also changes the
entire repository test merge policy. A small dedicated required check is more
precise. Rejected for this scope.

## Explicit YAGNI boundaries

- One existing allocator owner is extended; no allocation service or database.
- The GitHub API is read-only.
- No configuration knobs for numbering width, directories, or collision policy.
- No automatic commit, push, PR labeling, readiness transition, or merge.
- No retry queue. CI fails with a clear diagnostic and GitHub's normal rerun is
  the retry mechanism.
- No attempt to make local hooks a security boundary; the required PR check is
  authoritative.

## Acceptance criteria

The design is implemented only when all of the following are true:

- A locally coordinated agent cannot commit a new numeric ADR without owning
  that reservation.
- A degraded local allocator produces `XXXX`, not an unverified number.
- A ready PR with `XXXX` fails.
- A PR colliding with `main` or any open PR fails with exact provenance.
- GitHub-state failure makes the policy check fail.
- A unique manual or fork-authored ADR can pass without the local registry.
- `main` rejects duplicates and placeholders.
- `adr-policy` is required by the active default-branch ruleset with no bypass
  actor.
- ADR-0110, the README, and the `new-adr` skill describe the same workflow.
