# ADR Number Allocation Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ADR-number collisions unmergeable on every AutoGIS pull request while preserving useful local authoring: coordinated sessions reserve numeric IDs, degraded allocation produces `XXXX`, ready PRs must finalize placeholders, and the active default-branch ruleset requires the fail-closed `adr-policy` check.

**Architecture:** Keep `.claude/skills/new-adr/next_adr_number.py` as the single ADR-policy owner. Add pure path/policy functions, a small paginated `gh api` reader, a CI entry point, and transactional finalization there. Reuse the existing coordination registry through `coord reserve-adr --strict`; extend the commit hook only as a local early-warning guard. GitHub Actions is the universal authority, and `RulesForThee` makes that job load-bearing.

**Tech Stack:** Python 3.11 stdlib (`argparse`, `json`, `os`, `re`, `subprocess`, `sys`, `pathlib`, `typing`), existing coordination registry, GitHub CLI REST client, GitHub Actions, pytest, and PyYAML already present in the dev extras. No ArcPy and no new dependency.

## Global Constraints

- Binding design: `docs/superpowers/specs/2026-08-13-adr-number-enforcement-design.md`.
- Incident evidence: issue #492 and the former collision between PRs #487 and #488. The immediate incident is closed; this work is the systemic enforcement follow-up.
- Work only in an isolated claimed worktree on a feature branch. `main` remains read-only. Before implementation, refresh `origin/main`, rebase or recreate the worktree if needed, run `python .claude/coordination/coord_cli.py resync`, and claim every file before editing it.
- Follow `AGENTS.md`: run `sonar analyze secrets <path>` before reading each workspace file. Keep the full `ponytail` skill active.
- Do not touch the untracked `.agents/.codex` mirror. The tracked owner is `.claude/skills/new-adr/`.
- Preserve existing CLI behavior: no arguments prints the next fail-soft informational number; `--base` prints the fail-soft scan floor; `--check` runs the self-check.
- Sequential IDs remain four-digit `NNNN`; root-level dated files, `README.md`, `TEMPLATE.md`, `docs/adr/logs/`, and `XXXX` are not numeric claims.
- A file status claims a new number only when GitHub or staged Git reports it as added or renamed. A modified existing path and a removed path do not claim a number.
- CI must fail closed on incomplete GitHub state. Local informational numbering remains fail-soft. Local commit-hook inspection remains fail-open on unexpected internal errors because it is not the authority.
- The GitHub reader must request every open-PR page and every changed-file page. GitHub's REST file-list endpoint caps a PR at 3,000 files; seeing 3,000 entries is therefore unverifiable and must fail closed.
- Never log tokens, response headers, full GitHub payloads, or raw authenticated command lines. Diagnostics may include endpoint purpose, PR number, HTTP/CLI exit status, or exception class.
- The policy job must use the exact required-check context `adr-policy` for base-controlled `pull_request_target` and `push` runs only. A `workflow_dispatch` or candidate-controlled `pull_request` run must not be able to satisfy that context.
- The read-only `pull_request_target` job may execute only the trusted base checker against a credential-free candidate checkout treated as data. No bot write, candidate-code execution, merge queue, automatic commit/push, PR state transition, label, or merge behavior.
- No new ADR. Amend ADR-0110 because this is enforcement of its existing tooling decision.
- Use `python -m pytest ... -q -p no:cacheprovider` for focused tests. The final full suite remains arcpy-free.

---

## File and Interface Map

| File | Responsibility |
|---|---|
| `.claude/skills/new-adr/next_adr_number.py` | Root ADR recognition, pure policy validation, paginated GitHub state, fail-soft/strict allocation, `--policy-check`, and `--finalize` |
| `tests/test_adr_policy.py` | All pure policy, fake-GitHub, CLI, finalization, workflow-contract, and issue-#492 regression tests |
| `.claude/coordination/coord_cli.py` | Add `reserve-adr --strict` and propagate authoritative-scan failure without creating a reservation |
| `tests/coordination/test_coord_cli.py` | Strict/fail-soft reservation behavior and caller-worktree regression coverage |
| `.claude/coordination/hook_check.py` | Inspect staged added/renamed numeric ADRs on `git commit` and require the current session's matching live reservation |
| `tests/coordination/test_hook_check.py` | Reservation ownership, staged status, rename, placeholder, modification, and fail-open hook tests |
| `.github/workflows/adr-policy.yml` | Base-controlled dependency-free `adr-policy` job, trusted checker, and separate candidate checkout |
| `.github/workflows/ci.yml` | Candidate-controlled pytest workflow; must not emit the required `adr-policy` context |
| `.claude/skills/new-adr/SKILL.md` | Reservation-first creation, `XXXX` fallback, and finalization instructions |
| `docs/adr/README.md` | One consistent author workflow and merge-state rules |
| `docs/adr/0110-ci-and-agent-tooling-batch.md` | 2026-08-13 enforcement amendment tied to #492/#487/#488 |

Keep `.claude/coordination/registry.py` and `tests/test_adr_numbering.py` unchanged unless implementation proves a shared helper is strictly necessary. `registry.list_claims`, `registry.reserve_number`, and `registry.release` already provide the required primitives; the existing numbering test remains the merged-tree invariant.

---

### Task 1: Add pure ADR path and PR-policy validation

**Files:**
- Modify: `.claude/skills/new-adr/next_adr_number.py`
- Create: `tests/test_adr_policy.py`

**Interfaces:**

```python
class PRFile(NamedTuple):
    pr_number: int
    path: str
    status: str


def _adr_number(path: str) -> int | None:
    """Return a root-level real ADR number, excluding dated names."""


def _is_placeholder(path: str) -> bool:
    """Whether path is exactly docs/adr/XXXX-<slug>.md."""


def _tree_policy_errors(paths: Iterable[str], *, allow_placeholders: bool) -> list[str]:
    """Return deterministic duplicate/placeholder errors for one tree."""


def _pull_request_policy_errors(
    *,
    current_pr: int,
    draft: bool,
    current_files: Sequence[PRFile],
    base_paths: Sequence[str],
    other_files: Sequence[PRFile],
) -> list[str]:
    """Return deterministic current-vs-base/current-vs-open-PR errors."""
```

- [ ] **Step 1: Create the test loader and failing recognition tests**

Load the hidden script without changing global pytest configuration:

```python
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / ".claude" / "skills" / "new-adr" / "next_adr_number.py"
)
SPEC = spec_from_file_location("autogis_next_adr_number", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
adr = module_from_spec(SPEC)
sys.modules[SPEC.name] = adr
SPEC.loader.exec_module(adr)
```

Add parameterized tests proving:

```python
@pytest.mark.parametrize(
    ("path", "number", "placeholder"),
    [
        ("docs/adr/0129-one.md", 129, False),
        ("docs\\adr\\0130-two.md", 130, False),
        ("docs/adr/2026-08-13-agent-decisions.md", None, False),
        ("docs/adr/logs/0129-log.md", None, False),
        ("docs/adr/README.md", None, False),
        ("docs/adr/TEMPLATE.md", None, False),
        ("docs/adr/XXXX-draft.md", None, True),
        ("other/0129-one.md", None, False),
    ],
)
def test_root_adr_recognition(path, number, placeholder):
    assert adr._adr_number(path) == number
    assert adr._is_placeholder(path) is placeholder
```

- [ ] **Step 2: Add failing policy matrices**

Cover all of these with exact diagnostics:

- duplicate numbers in one checkout;
- a placeholder allowed in a draft PR and rejected in a ready PR;
- a placeholder rejected on `main`;
- current PR versus a differently named base ADR with the same number;
- current PR versus a differently named ADR added by another open PR;
- two numeric ADRs with one prefix in the current PR;
- multiple collisions sorted by number, then path, then PR number;
- a same-path `modified` file in base/current/other PRs ignored as a new claim;
- `removed` files ignored;
- a `renamed` file's new `filename` treated as a claim; and
- the exact #487/#488 shape:

```python
def test_issue_492_distinct_0129_slugs_cannot_both_pass():
    errors = adr._pull_request_policy_errors(
        current_pr=488,
        draft=False,
        current_files=[adr.PRFile(488, "docs/adr/0129-registry-metadata.md", "added")],
        base_paths=[],
        other_files=[adr.PRFile(487, "docs/adr/0129-connection-profile.md", "added")],
    )
    assert errors == [
        "ADR 0129 is also added by PR #487 as "
        "docs/adr/0129-connection-profile.md; use XXXX or finalize after "
        "that claim changes."
    ]
```

- [ ] **Step 3: Run the new tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_adr_policy.py -q -p no:cacheprovider
```

Expected: collection or attribute failures because `PRFile`, `_adr_number`, `_is_placeholder`, and the validators do not exist.

- [ ] **Step 4: Implement only the pure recognition and validation layer**

Normalize separators, then require exactly one filename component beneath `docs/adr/`. Reuse `_num()` for dated-name exclusion. Define `_CLAIM_STATUSES = {"added", "renamed"}`. Build maps keyed by integer number and compare different normalized paths only. Return messages in a final `sorted()` order; never print from pure functions.

Use these stable message forms:

```text
Duplicate ADR 0129 in checked-out tree: docs/adr/0129-a.md, docs/adr/0129-b.md.
docs/adr/XXXX-new-policy.md is unfinalized; ready PRs require numeric ADR filenames.
docs/adr/XXXX-new-policy.md is unfinalized; main may not contain ADR placeholders.
ADR 0129 already exists on the base branch as docs/adr/0129-existing.md; docs/adr/0129-new.md must use a different number.
ADR 0129 is also added by PR #487 as docs/adr/0129-other.md; use XXXX or finalize after that claim changes.
```

- [ ] **Step 5: Run the pure-policy tests and confirm GREEN**

Run the same focused command. Expected: all tests in `tests/test_adr_policy.py` pass without network access.

- [ ] **Step 6: Commit the pure policy slice**

```powershell
git add .claude/skills/new-adr/next_adr_number.py tests/test_adr_policy.py
git commit -m "feat: define ADR pull-request policy"
```

---

### Task 2: Add complete GitHub state and the fail-closed policy command

**Files:**
- Modify: `.claude/skills/new-adr/next_adr_number.py`
- Modify: `tests/test_adr_policy.py`

**Interfaces:**

```python
class ADRStateUnavailable(RuntimeError):
    """Authoritative GitHub ADR state could not be proven complete."""


def _gh_object(endpoint: str, *, run=None) -> dict:
    """Read one GitHub REST object through gh api."""


def _gh_pages(endpoint: str, *, run=None) -> list[dict]:
    """Flatten gh api --paginate --slurp pages after shape validation."""


def _base_paths(ref: str, *, run=None) -> list[str]:
    """Read an untruncated Git tree for the PR base SHA/ref."""


def _pull_files(pr_number: int, *, run=None) -> list[PRFile]:
    """Read all changed-file pages; reject an unverifiable 3,000-file result."""


def _open_pull_numbers(*, run=None) -> list[int]:
    """Read every open pull-request page."""


def policy_check(
    repo_root: Path,
    *,
    event_name: str,
    event: dict,
    run=None,
) -> list[str]:
    """Validate checkout plus authoritative PR/base/open-PR state."""
```

- [ ] **Step 1: Add a deterministic fake runner and failing pagination tests**

The fake runner maps the REST endpoint argument to either JSON or a controlled failure and records every call. Test that `--paginate --slurp` is present for both:

```text
repos/{owner}/{repo}/pulls?state=open&per_page=100
repos/{owner}/{repo}/pulls/<number>/files?per_page=100
```

Cover:

- two open-PR pages;
- two changed-file pages for one PR;
- current PR excluded from the other-PR collection;
- malformed outer JSON and malformed page/item shapes;
- `FileNotFoundError`, timeout, nonzero `gh` exit, and a simulated later-page failure;
- a base Git-tree response with `truncated: true`;
- 3,000 returned PR files treated as incomplete, not successful; and
- errors containing the exception class/exit code but not response payloads or tokens.

- [ ] **Step 2: Add failing event/CLI tests**

Use temporary event JSON for:

```json
{
  "pull_request": {
    "number": 488,
    "draft": false,
    "base": {"sha": "1111111111111111111111111111111111111111"}
  }
}
```

Assert:

- pull-request mode invokes local-tree, current-file, base-tree, open-PR, and other-file validation;
- push mode performs the `main` tree invariant without GitHub reads;
- policy violations exit `1`;
- unavailable/malformed GitHub state exits `2`;
- success exits `0` and prints a short success line; and
- `--event-file` overrides `GITHUB_EVENT_PATH` and explicitly selects
  pull-request mode for rollout auditing/tests.

- [ ] **Step 3: Run the focused tests and confirm RED**

```powershell
python -m pytest tests/test_adr_policy.py -q -p no:cacheprovider
```

Expected: missing GitHub client, `policy_check`, and CLI modes.

- [ ] **Step 4: Implement the GitHub reader**

Use `subprocess.run` directly, with `run=None` parameters resolved inside each function so existing monkeypatches of `subprocess.run` still work. Use a 30-second timeout. `gh api --paginate --slurp` returns an outer list of pages; validate every level before flattening.

For a PR event:

1. Parse `number`, `draft`, and `base.sha` from the event.
2. Read current PR files completely.
3. Read the base Git tree and reject `truncated: true`.
4. Read every open PR number.
5. Read every other open PR's files completely.
6. Run `_tree_policy_errors(..., allow_placeholders=True)` and `_pull_request_policy_errors(...)`.

For `push`, run only `_tree_policy_errors(..., allow_placeholders=False)`. For an unsupported/missing CI event, raise `ADRStateUnavailable` instead of silently selecting a weaker mode.

- [ ] **Step 5: Replace the incomplete open-PR maximum scan without breaking fail-soft callers**

Refactor `_open_pr_max()` to use the same paginated file reader. Keep its default behavior:

```python
def _open_pr_max(*, strict: bool = False, run=None) -> int:
    try:
        files = _all_open_pull_files(run=run)
    except ADRStateUnavailable as exc:
        if strict:
            raise
        print(_NO_GH_WARNING.format(why=type(exc).__name__), file=sys.stderr)
        return 0
    return max((_adr_number(item.path) or 0 for item in files), default=0)
```

Do not expose a partial maximum after any page fails.

- [ ] **Step 6: Convert the script footer to `argparse` while preserving old modes**

Use one mutually exclusive group for `--check`, `--base`, and
`--policy-check`; Task 4 adds `--finalize` to that same group. No mode still
prints `next_adr_number()` in four-digit form. `main(argv=None, environ=None,
run=None) -> int` must be directly testable; the module footer is only
`sys.exit(main())`.

- [ ] **Step 7: Run scanner self-check and tests**

```powershell
python .claude/skills/new-adr/next_adr_number.py --check
python -m pytest tests/test_adr_policy.py tests/test_adr_numbering.py -q -p no:cacheprovider
```

Expected: self-check OK; all policy/numbering tests pass offline.

- [ ] **Step 8: Commit the authoritative policy slice**

```powershell
git add .claude/skills/new-adr/next_adr_number.py tests/test_adr_policy.py
git commit -m "feat: check ADR claims across pull requests"
```

---

### Task 3: Make numeric local allocation reservation-first and strict

**Files:**
- Modify: `.claude/skills/new-adr/next_adr_number.py`
- Modify: `.claude/coordination/coord_cli.py`
- Modify: `tests/test_adr_policy.py`
- Modify: `tests/coordination/test_coord_cli.py`

**Interfaces:**

```python
def _scan_max(root: Path, *, strict: bool = False, run=None) -> int:
    """Highest local/base/open-PR number; strict mode requires all remote state."""


def _adr_scan_base(cwd, strict=False):
    """Coordination floor; strict mode propagates any authoritative-scan failure."""
```

CLI addition:

```text
coord reserve-adr [--session SID] [--strict]
```

- [ ] **Step 1: Add failing strict-scan tests**

Prove `_scan_max(root, strict=True)` includes:

- numeric ADRs in the caller checkout;
- numeric ADRs on the authoritative default branch, even when the checkout is stale;
- numeric ADRs added/renamed by every open PR; and
- no removed, dated, nested-log, or placeholder paths.

Also prove any GitHub failure raises `ADRStateUnavailable` and does not return the local floor.

- [ ] **Step 2: Add failing coordination CLI tests**

Update existing `_adr_scan_base` monkeypatch lambdas to accept `strict=False`. Add tests asserting:

```python
def test_strict_reserve_adr_does_not_claim_when_scan_fails(
        tmp_path, monkeypatch, capsys):
    def fail(_cwd, strict=False):
        assert strict is True
        raise RuntimeError("authoritative scan unavailable")

    monkeypatch.setattr(coord_cli, "_adr_scan_base", fail)
    registry_path = tmp_path / "claims.json"
    rc = coord_cli.run(
        ["reserve-adr", "--session", "s1", "--strict"], registry_path
    )
    assert rc == 2
    assert registry.live_values(registry_path, "adr") == []
    assert "no ADR number was reserved" in capsys.readouterr().err
```

Retain tests proving non-strict `reserve-adr` still prints a number and warning when `gh` is unavailable.

- [ ] **Step 3: Run both files and confirm RED**

```powershell
python -m pytest tests/test_adr_policy.py tests/coordination/test_coord_cli.py -q -p no:cacheprovider
```

- [ ] **Step 4: Implement strict remote-base scanning**

For strict allocation, query `repos/{owner}/{repo}` for `default_branch`, query that branch's complete Git tree, and combine it with the complete open-PR file collection and local caller tree. Reject missing `default_branch`, truncated trees, malformed responses, and any page failure.

For fail-soft informational allocation, retain today's local + open-PR warning behavior. A fail-soft answer is display-only and never authorizes a numeric ADR.

- [ ] **Step 5: Add `--strict` to `reserve-adr`**

Parse the flag only on the `reserve-adr` subcommand. In strict mode, call `_adr_scan_base(cwd, strict=True)` before `registry.reserve_number`. On any exception, print a sanitized one-line diagnostic to stderr, return `2`, and never call `reserve_number`. Non-strict behavior remains backward-compatible.

- [ ] **Step 6: Run focused coordination regression tests**

```powershell
python -m pytest tests/test_adr_policy.py tests/coordination/test_coord_cli.py tests/coordination/test_registry.py -q -p no:cacheprovider
```

- [ ] **Step 7: Commit the strict allocation slice**

```powershell
git add .claude/skills/new-adr/next_adr_number.py .claude/coordination/coord_cli.py tests/test_adr_policy.py tests/coordination/test_coord_cli.py
git commit -m "feat: require verified ADR reservations"
```

---

### Task 4: Add strict, transactional placeholder finalization

**Files:**
- Modify: `.claude/skills/new-adr/next_adr_number.py`
- Modify: `tests/test_adr_policy.py`

**Interfaces:**

```python
class FinalizedADR(NamedTuple):
    old_path: Path
    new_path: Path


def finalize_placeholders(
    repo_root: Path,
    *,
    environ=None,
    run=None,
    write_bytes=None,
) -> list[FinalizedADR]:
    """Strictly allocate, validate, reserve when coordinated, and rewrite XXXX ADRs."""
```

- [ ] **Step 1: Build temporary-repository fixtures and failing success tests**

Each placeholder fixture must contain:

```markdown
# ADR-XXXX: Example Decision
```

and one index row:

```markdown
| [XXXX](XXXX-example-decision.md) | Example decision | Proposed | 2026-08-13 |
```

Add tests for:

- one placeholder becoming `0131-example-decision.md`, `# ADR-0131`, and `[131](0131-example-decision.md)` when the strict floor is 130;
- multiple placeholders assigned consecutive numbers in filename/slug sort order;
- all returned mappings and printed mappings sorted deterministically;
- a strict floor raised by stale-checkout base/open-PR claims; and
- targets already existing rejected before any write.

- [ ] **Step 2: Add failing preflight/rollback tests**

Snapshot every fixture file's bytes and assert byte identity after:

- current branch is `main` or detached;
- no root placeholder exists;
- strict GitHub scan failure;
- malformed/missing `# ADR-XXXX` first line;
- missing or duplicate README index entries;
- duplicate transformed numeric prefixes;
- a simulated failure after one ADR rewrite; and
- a simulated README write failure.

Also assert any reservations created by this invocation are released on validation/application failure and retained on success.

- [ ] **Step 3: Run the finalizer tests and confirm RED**

```powershell
python -m pytest tests/test_adr_policy.py -q -p no:cacheprovider
```

- [ ] **Step 4: Implement a no-write preflight**

Perform these in order:

1. Resolve `git branch --show-current`; reject `main` and detached HEAD.
2. Discover every root `docs/adr/XXXX-*.md`, sorted by filename.
3. Read all placeholders and `docs/adr/README.md` into memory.
4. Validate each first line with `^# ADR-XXXX(?![A-Z0-9])`.
5. Require exactly one table-row link matching each exact placeholder filename.
6. Perform `_scan_max(repo_root, strict=True)` and include `_reserved_max()`.
7. Resolve the current coordination session through `coord_cli.resolve_sid` when the coordination package is available.
8. If coordinated, reserve one number per placeholder atomically with `registry.reserve_number`; otherwise allocate above the verified floor and live reservations in memory.
9. Build every new filename, H1, and index line in memory. Index labels use three-digit display (`131`) while filenames/H1 use four digits (`0131`).
10. Re-run numeric uniqueness and H1/filename consistency against the fully transformed in-memory tree.

If a coordination session is resolved but reservation storage fails, abort. Do not produce an unreserved numeric ADR that the commit hook will reject. If validation after reservation fails, release only the `kind=adr` values created by this invocation.

- [ ] **Step 5: Implement the reversible apply phase**

Keep original bytes for every touched path. Assert each numeric target is absent. Apply planned writes/renames only after preflight succeeds. On the first exception:

1. remove only numeric targets created by this invocation;
2. restore every original placeholder and README byte-for-byte;
3. release reservations created by this invocation; and
4. raise a sanitized error so CLI exits nonzero.

The injected `write_bytes` seam exists only to simulate one-shot I/O failure; production defaults to `Path.write_bytes`. Do not add a transaction class or dependency.

- [ ] **Step 6: Wire `--finalize`**

On success, print:

```text
docs/adr/XXXX-example-decision.md -> docs/adr/0131-example-decision.md
updated docs/adr/README.md
```

Return `0`. On policy/preflight/state/I/O error, return `2`. Do not stage, commit, push, mark ready, or merge.

- [ ] **Step 7: Run finalizer and existing numbering tests**

```powershell
python -m pytest tests/test_adr_policy.py tests/test_adr_numbering.py tests/coordination/test_coord_cli.py tests/coordination/test_registry.py -q -p no:cacheprovider
```

- [ ] **Step 8: Commit the finalizer slice**

```powershell
git add .claude/skills/new-adr/next_adr_number.py tests/test_adr_policy.py
git commit -m "feat: finalize ADR placeholders transactionally"
```

---

### Task 5: Block unreserved numeric ADR commits in coordinated sessions

**Files:**
- Modify: `.claude/coordination/hook_check.py`
- Modify: `tests/coordination/test_hook_check.py`

**Interfaces:**

```python
def _staged_numeric_adrs(cwd):
    """Return [("0131", "docs/adr/0131-slug.md")] for staged A/R paths.

    Return None when staged-diff inspection is unavailable so the local hook
    retains its documented fail-open ceiling.
    """
```

Extend the test seam only:

```python
def decide(
    payload,
    reg_path,
    branch_func=None,
    main_tree_func=None,
    staged_func=None,
):
```

- [ ] **Step 1: Add failing decision tests with an injected staged reader**

Cover:

- own live `kind=adr`, value `131` permits staged `0131-*`;
- no reservation denies;
- another session's reservation denies;
- a stale own reservation denies;
- multiple numeric ADRs require one matching reservation each;
- an `XXXX` path is allowed;
- `None` from staged inspection allows (documented fail-open); and
- existing main/branch denials still take precedence.

Assert the stable denial includes both number and path:

```text
[coord] ADR 0131 is staged as docs/adr/0131-example.md without this session owning reservation 0131; run coord reserve-adr --strict or rename the file to XXXX-example.md.
```

- [ ] **Step 2: Add real temporary-git tests for status selection**

Reuse the real-git style already at the bottom of `test_hook_check.py`. Initialize a repository and prove:

- staged added numeric ADR returned;
- staged rename to a new numeric ADR returned with the destination path;
- staged modification of the same tracked numeric ADR ignored;
- staged removal ignored; and
- staged `XXXX` addition ignored.

Use:

```text
git -C <repo> diff --cached --name-status --diff-filter=AR
```

Parse tab-separated records and use the last field as the destination path. ADR naming disallows tabs/newlines, so a shell-language parser is unnecessary.

- [ ] **Step 3: Run hook tests and confirm RED**

```powershell
python -m pytest tests/coordination/test_hook_check.py -q -p no:cacheprovider
```

- [ ] **Step 4: Implement the staged guard in the existing `git commit` path**

After resolving a non-foreign commit target and applying existing main/branch checks:

1. call `staged_func or _staged_numeric_adrs` for that target;
2. if it returns `None`, continue without denial;
3. collect live claims with `registry.list_claims(reg_path)`;
4. normalize numeric claim values through `int` so `131` matches `0131`;
5. require `session_id == sid`, `kind == "adr"`, and matching value; and
6. deny on the first sorted missing reservation.

Do not apply this rule to merge/rebase/cherry-pick/revert. Those operations can create commits without introducing a newly staged authoring choice, and the required CI policy remains authoritative.

- [ ] **Step 5: Run the complete coordination suite**

```powershell
python -m pytest tests/coordination -q -p no:cacheprovider
```

- [ ] **Step 6: Commit the hook slice**

```powershell
git add .claude/coordination/hook_check.py tests/coordination/test_hook_check.py
git commit -m "feat: guard numeric ADR commits with reservations"
```

---

### Task 6: Wire the dependency-free `adr-policy` GitHub Actions job

**Files:**
- Create: `.github/workflows/adr-policy.yml`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_adr_policy.py`

- [ ] **Step 1: Add failing workflow-contract tests**

Parse YAML with `yaml.BaseLoader` so the YAML 1.1 `on` key remains the string `"on"`. Assert:

- `pull_request_target.types` is exactly the set `opened`, `synchronize`, `reopened`, `ready_for_review`, `converted_to_draft`;
- job key `adr-policy` exists;
- PR/push check name resolves to literal `adr-policy`;
- `workflow_dispatch` is excluded or named differently, so it cannot create the required context;
- runner is `windows-2022`;
- permissions are exactly read-only `contents` and `pull-requests`;
- no install command or cache is present;
- the trusted base checker runs with `--policy-check --repo-root candidate`;
- both checkouts persist no credentials;
- only the candidate checkout sets `allow-unsafe-pr-checkout: true`, allowing
  fork content to be fetched as data without executing it;
- candidate `ci.yml` has no `adr-policy` job; and
- `GH_TOKEN` comes from `${{ github.token }}`.

- [ ] **Step 2: Run the workflow-contract test and confirm RED**

```powershell
python -m pytest tests/test_adr_policy.py -q -p no:cacheprovider
```

- [ ] **Step 3: Add the triggers and job**

Retain `workflow_dispatch` and ordinary `pull_request` for candidate pytest in
`ci.yml`. Put the required check in standalone `adr-policy.yml`, using this
base-controlled shape:

```yaml
  adr-policy:
    name: ${{ github.event_name == 'workflow_dispatch' && 'adr-policy-manual' || 'adr-policy' }}
    if: github.event_name != 'workflow_dispatch'
    runs-on: windows-2022
    timeout-minutes: 5
    permissions:
      contents: read
      pull-requests: read
    steps:
      - name: Checkout trusted policy
        uses: actions/checkout@v7
        with:
          ref: ${{ github.event_name == 'pull_request_target' && github.event.pull_request.base.sha || github.sha }}
          path: trusted-policy
          persist-credentials: false
      - name: Checkout candidate tree
        uses: actions/checkout@v7
        with:
          ref: ${{ github.event_name == 'pull_request_target' && format('refs/pull/{0}/merge', github.event.pull_request.number) || github.sha }}
          path: candidate
          persist-credentials: false
          allow-unsafe-pr-checkout: true
      - uses: actions/setup-python@v7
        with:
          python-version: "3.11"
      - name: Enforce ADR allocation policy
        env:
          GH_TOKEN: ${{ github.token }}
        run: python trusted-policy/.claude/skills/new-adr/next_adr_number.py --policy-check --repo-root candidate
```

The distinct manual name and standalone base-controlled workflow are
load-bearing: neither a green manual run nor candidate-edited `ci.yml` may
satisfy the `adr-policy` ruleset requirement. The introduction PR needs one
owner-authorized bootstrap merge because this trigger cannot run until the
workflow exists on the base branch; no later PR receives that bypass.

- [ ] **Step 4: Run focused tests and inspect parsed workflow**

```powershell
python -m pytest tests/test_adr_policy.py tests/test_adr_numbering.py -q -p no:cacheprovider
```

- [ ] **Step 5: Commit the workflow slice**

```powershell
git add .github/workflows/adr-policy.yml .github/workflows/ci.yml tests/test_adr_policy.py
git commit -m "ci: enforce ADR allocation policy"
```

---

### Task 7: Reconcile author guidance and amend ADR-0110

**Files:**
- Modify: `.claude/skills/new-adr/SKILL.md`
- Modify: `docs/adr/README.md`
- Modify: `docs/adr/0110-ci-and-agent-tooling-batch.md`

- [ ] **Step 1: Update the `new-adr` skill to one decision tree**

Replace optional reservation guidance with:

```powershell
python .claude/coordination/coord_cli.py reserve-adr --strict --session $env:AUTOGIS_SESSION_ID
```

Document exact behavior:

1. A successful command authorizes the printed numeric filename.
2. Session resolution or strict GitHub scan failure means create `XXXX-<slug>.md`, never use the fail-soft suggestion.
3. Add `# ADR-XXXX` and one `[XXXX](XXXX-<slug>.md)` index row for a placeholder.
4. Before making the PR ready, run:

```powershell
python .claude/skills/new-adr/next_adr_number.py --finalize
```

5. Review the mapping, stage/commit normally, and release reservations after merge.

Keep the no-arguments allocator documented as informational only.

- [ ] **Step 2: Reconcile `docs/adr/README.md`**

Replace the current competing “parallel branches use `XXXX`” wording with the same state model:

- coordinated + verified + reserved -> numeric ADR;
- unavailable verification/session -> `XXXX` draft;
- draft PR may retain `XXXX`;
- ready PR and `main` may not;
- `--finalize` performs the filename/H1/index rewrite; and
- `adr-policy` is the universal merge gate for human, remote, and fork PRs.

- [ ] **Step 3: Add a dated amendment to ADR-0110**

Add `### Amendment — required ADR allocation enforcement (2026-08-13)` after the original reservation decision. State that:

- issue #492 exposed PRs #487/#488 both claiming 0129;
- reservations remain the local pre-PR race defense;
- `XXXX` is now the explicit degraded/draft state, not a competing allocator;
- strict finalization updates filename/H1/index;
- paginated, fail-closed `adr-policy` covers every PR; and
- the active default-branch ruleset must require that check.

Explicitly say this amendment supersedes the original claim that reservation alone was sufficient; it does not erase the historical rationale.

- [ ] **Step 4: Check cross-document consistency**

Run searches and manually compare the three files:

```powershell
rg -n "reserve-adr|--strict|XXXX|--finalize|adr-policy|#492|#487|#488" .claude/skills/new-adr/SKILL.md docs/adr/README.md docs/adr/0110-ci-and-agent-tooling-batch.md
```

Expected: all describe the same reservation-first/fallback/finalization/required-check sequence; none says reservation is optional for a coordinated numeric ADR.

- [ ] **Step 5: Commit the documentation slice**

```powershell
git add .claude/skills/new-adr/SKILL.md docs/adr/README.md docs/adr/0110-ci-and-agent-tooling-batch.md
git commit -m "docs: define enforced ADR allocation workflow"
```

---

### Task 8: Run local verification and cold review before publication

**Files:** All changed files from Tasks 1-7.

- [ ] **Step 1: Run required secrets scans on every changed file**

```powershell
git diff --name-only origin/main...HEAD
```

Run `sonar analyze secrets <path>` separately for every result. Stop if any scan reports a secret.

- [ ] **Step 2: Run the focused ADR/coordination suite**

```powershell
python -m pytest tests/test_adr_numbering.py tests/test_adr_policy.py tests/coordination/test_coord_cli.py tests/coordination/test_registry.py tests/coordination/test_hook_check.py -q -p no:cacheprovider
```

- [ ] **Step 3: Run script-level smoke checks**

```powershell
python .claude/skills/new-adr/next_adr_number.py --check
python .claude/skills/new-adr/next_adr_number.py
python .claude/skills/new-adr/next_adr_number.py --base
```

The latter two may warn only in a genuinely degraded local environment; stdout remains one machine-readable number.

- [ ] **Step 4: Run the full arcpy-free suite**

```powershell
python -m pytest -q -n auto --durations=20 -p no:cacheprovider
```

- [ ] **Step 5: Run repository hygiene checks**

```powershell
git diff --check origin/main...HEAD
git status --short
```

Expected: no whitespace errors, no generated cache files, no edits outside the file map, and a clean worktree after verification commits.

- [ ] **Step 6: Self-review against every design acceptance criterion**

Record evidence for:

- unreserved coordinated numeric commit denied;
- degraded allocation creates no number/reservation and skill instructs `XXXX`;
- ready placeholder rejected; draft placeholder allowed;
- base/open-PR collision with provenance;
- unavailable GitHub state exits nonzero;
- unique manual/fork ADR requires no local registry in CI;
- main duplicate/placeholder rejected;
- no manual-dispatch required-check bypass;
- docs agree; and
- no product/ArcPy/dependency changes.

- [ ] **Step 7: Request an independent cold review**

Use the repository's `pr-reviewer` agent after implementation is complete. Require an APPROVE/REQUEST CHANGES verdict against the exact head SHA, the focused/full test results, the required-check bypass analysis, and the design spec. Address any demonstrated issue, then rerun affected tests and refresh the reviewed SHA.

---

### Task 9: Publish the implementation PR and verify the new check

This task changes remote state. Execute it only after the user has authorized implementation publication.

- [ ] **Step 1: Rebase safely and rerun focused verification if `origin/main` moved**

Do not merge a stale implementation branch. Preserve unrelated user work and coordination claims.

- [ ] **Step 2: Push and open the PR**

The PR body must include:

- `Refs #492` (the issue is already closed);
- the #487/#488 regression test;
- focused and full-suite evidence;
- why `adr-policy` is separate from `pytest`;
- why manual workflow dispatch cannot satisfy the required context; and
- a rollout checklist showing the ruleset update is still pending.

- [ ] **Step 3: Verify hosted checks and the documented bootstrap condition**

```powershell
gh pr checks <implementation-pr-number> --watch
```

Confirm all checks that can run from the current base are green on the exact
reviewed head. The native `adr-policy` context is expected to be absent on this
introduction PR because the base-controlled workflow does not yet exist on
`main`; absence is neither success nor evidence that the later rule is active.

- [ ] **Step 4: Audit every currently open PR with the same policy command**

Use `gh api --paginate --slurp "repos/{owner}/{repo}/pulls?state=open&per_page=100"` to obtain every open PR. For each PR, synthesize a temporary event containing its `number`, `draft`, and `base.sha`, then run:

```powershell
python .claude/skills/new-adr/next_adr_number.py --policy-check --event-file <temporary-event.json>
```

Passing `--event-file` selects pull-request mode even outside GitHub Actions;
the temporary payload is therefore sufficient without mutating process-wide
GitHub event variables.

Delete only the exact temporary event after each run. Record any existing collision or ready placeholder before enabling the rule. Do not fix unrelated PRs without separate authority; report them.

- [ ] **Step 5: Confirm all actionable review threads are resolved and re-verify the final head**

Use thread-aware review retrieval, not flat comments. The ruleset mutation must not proceed against an unreviewed or red implementation head.

---

### Task 10: Allow fork candidate data checkout without widening execution

**Files:**
- Modify: `.github/workflows/adr-policy.yml:31-36`
- Test: `tests/test_adr_policy.py:36-84`
- Modify: `docs/adr/0110-ci-and-agent-tooling-batch.md`

**Interfaces:**
- Consumes: the existing exact parsed-workflow contract in
  `test_adr_policy_workflow_contract()` and `actions/checkout@v7` input
  `allow-unsafe-pr-checkout`.
- Produces: a candidate checkout that can fetch fork merge refs while remaining
  credential-free and data-only; the trusted policy checkout does not opt in.

- [ ] **Step 1: Write the failing candidate-only opt-in regression**

Add this test beside the existing workflow contract:

```python
def test_only_candidate_checkout_opts_into_fork_content():
    steps = _adr_workflow()["jobs"]["adr-policy"]["steps"]
    trusted = next(step for step in steps if step.get("name") == "Checkout trusted policy")
    candidate = next(step for step in steps if step.get("name") == "Checkout candidate tree")

    assert "allow-unsafe-pr-checkout" not in trusted["with"]
    assert candidate["with"]["allow-unsafe-pr-checkout"] == "true"
    assert candidate["with"]["persist-credentials"] == "false"
```

Also add `"allow-unsafe-pr-checkout": "true"` only to the candidate step in
the exact `job["steps"]` expectation.

- [ ] **Step 2: Run the regression and confirm RED**

```powershell
python -m pytest tests/test_adr_policy.py::test_only_candidate_checkout_opts_into_fork_content -q -p no:cacheprovider
```

Expected: FAIL because the candidate checkout has no
`allow-unsafe-pr-checkout` input.

- [ ] **Step 3: Add the minimal workflow opt-in**

Under `Checkout candidate tree` only, retain `persist-credentials: false` and
add:

```yaml
          allow-unsafe-pr-checkout: true
```

Do not add the input to `Checkout trusted policy`. Do not execute, import, or
source anything from `candidate`; the trusted checker remains the only executed
repository code.

- [ ] **Step 4: Run workflow-contract tests and confirm GREEN**

```powershell
python -m pytest tests/test_adr_policy.py -k "workflow or candidate" -q -p no:cacheprovider
```

Expected: PASS, including both the exact step-list contract and the
candidate-only opt-in regression.

- [ ] **Step 5: Reconcile ADR-0110 with the approved trust boundary**

Add this consequence to the 2026-08-13 enforcement amendment:

```markdown
- Checkout v7's fork opt-in is set only on the credential-free candidate
  checkout. It permits fetching untrusted PR content as policy input; no
  candidate file is imported, invoked, or sourced.
```

- [ ] **Step 6: Run focused and full verification**

Use unique non-Git `%TEMP%` base directories:

```powershell
$focusedBase = Join-Path ([System.IO.Path]::GetTempPath()) ("autogis-pr506-focused-" + [guid]::NewGuid().ToString("N"))
python -m pytest tests/test_adr_policy.py tests/coordination/test_hook_check.py -q -p no:cacheprovider --basetemp $focusedBase
$fullBase = Join-Path ([System.IO.Path]::GetTempPath()) ("autogis-pr506-full-" + [guid]::NewGuid().ToString("N"))
python -m pytest -q -p no:cacheprovider --basetemp $fullBase
python .claude/skills/new-adr/next_adr_number.py --check
git diff --check
```

- [ ] **Step 7: Commit the reviewed fork-checkout slice**

```powershell
git add .github/workflows/adr-policy.yml tests/test_adr_policy.py docs/adr/0110-ci-and-agent-tooling-batch.md
git commit -m "fix: allow fork ADR policy checkout"
```

Request a fresh independent exact-head review. Do not resolve review threads or
merge until its verdict is APPROVE.

---

### Task 11: Bootstrap `adr-policy`, make it load-bearing, and verify

This task mutates repository settings and merges the PR. Execute it only with the user's explicit authorization for those remote actions.

- [ ] **Step 1: Re-resolve the active ruleset by name**

```powershell
gh api "repos/{owner}/{repo}/rulesets"
```

Require exactly one repository ruleset where:

```text
name = RulesForThee
target = branch
enforcement = active
```

Do not hardcode the previously observed ID `18357662`.

- [ ] **Step 2: Snapshot the full ruleset and assert preservation constraints**

```powershell
gh api "repos/{owner}/{repo}/rulesets/<resolved-id>"
```

Before mutation, verify:

- target condition remains `~DEFAULT_BRANCH`;
- bypass actors are empty;
- deletion protection remains;
- non-fast-forward protection remains; and
- the pull-request rule still requires review-thread resolution with its existing merge-method settings.

- [ ] **Step 3: Bootstrap-merge the exact reviewed head**

After all available hosted checks pass and every actionable thread is addressed,
merge only the exact independently reviewed head SHA using the owner's explicit
one-time admin authorization. If the head changed, return to Task 8 review and
verification. This bypass exists only because the base-controlled workflow is
not yet present on `main`.

- [ ] **Step 4: Verify the first trusted push run**

Confirm the reviewed head is reachable from `origin/main`, then watch the
push-to-main `.github/workflows/adr-policy.yml` run. Require its literal
`adr-policy` job to succeed before changing the ruleset.

- [ ] **Step 5: Add only the required-status-check rule**

Use GitHub Settings -> Rules -> Rulesets -> `RulesForThee` after re-resolving it. Add “Require status checks to pass,” select the exact successful `adr-policy` check, leave strict up-to-date policy disabled unless it was already enabled, and save. Do not alter any other rule or bypass actor.

The equivalent REST rule, if the UI is unavailable, is:

```json
{
  "type": "required_status_checks",
  "parameters": {
    "do_not_enforce_on_create": false,
    "required_status_checks": [{"context": "adr-policy"}],
    "strict_required_status_checks_policy": false
  }
}
```

When using REST `PUT`, rebuild the payload from the just-fetched live `name`, `target`, `enforcement`, `bypass_actors`, `conditions`, and complete `rules` array; append this rule and preserve every existing field. Never send a hardcoded historical payload.

- [ ] **Step 6: Verify the live ruleset after mutation**

Re-fetch it and assert:

- exactly one required-status-check rule;
- exactly one required context named `adr-policy` unless pre-existing contexts were intentionally preserved;
- empty bypass actors;
- `current_user_can_bypass` remains `never`; and
- deletion, non-fast-forward, PR, review-thread, conditions, target, and enforcement are byte-for-byte semantically unchanged.

If any preservation assertion fails, restore from the pre-mutation snapshot
through the same settings surface and report the incomplete rollout.

- [ ] **Step 7: Verify post-merge state**

After merge:

- confirm the reviewed head is reachable from `origin/main`;
- confirm the push-to-main `adr-policy` run passed on the merged head;
- re-fetch `RulesForThee` and confirm `adr-policy` is required with no bypass actor;
- confirm any subsequent PR without the context is blocked until its
  base-controlled run completes; and
- confirm no root `XXXX-*.md` and no duplicate numeric prefix exists on `main`.

The feature is incomplete if the ruleset cannot be updated or the required check is absent, even if all code is merged.

---

## Final Coverage Matrix

| Approved requirement | Implemented/tested in |
|---|---|
| Every PR, including manual/remote/fork | Tasks 2, 6, 10, 11 |
| Reservation-first local numeric ADR | Tasks 3, 5, 7 |
| Degraded allocation becomes `XXXX` | Tasks 3, 7 |
| Draft allows `XXXX`; ready rejects it | Tasks 1, 2, 6 |
| Base/open-PR collision provenance | Tasks 1, 2 |
| Complete pagination and fail-closed state | Task 2 |
| Strict filename/H1/index finalization | Task 4 |
| Main rejects duplicates/placeholders | Tasks 1, 2, 6 |
| Required dedicated check, no pytest broadening | Tasks 6, 10, 11 |
| No manual-dispatch status bypass | Task 6 |
| Preserve ruleset protections/no bypass actors | Task 11 |
| ADR-0110/README/skill agree | Task 7 |
| Historical #487/#488 regression | Task 1 |
