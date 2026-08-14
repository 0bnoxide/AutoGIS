#!/usr/bin/env python3
"""Pick the next free ADR number — checking local files, open PRs, AND origin/main.

Local `docs/adr/NNNN-*.md` only shows what's *merged*. Concurrent sessions
routinely pick the same NNNN and collide at merge (the 0099->0105 renumber is a
real example). This also scans open PR diffs for added `docs/adr/NNNN-*.md`.

Scope, honestly: this REDUCES collisions, it does not eliminate them. Two live
sessions that both grab NNNN *before either opens a PR* are invisible to a PR
scan — and that is exactly the recurring case. Fails soft: if `gh` is offline,
unauthed, or (cloud/web sessions) not installed at all, it degrades to the
local-only scan and says so on stderr — the degraded answer is still printed,
but the caller can now tell it apart from a guarded one (#454).

Usage:
    python next_adr_number.py          # prints next number, zero-padded (e.g. 0106)
    python next_adr_number.py --check   # run the self-check
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import NamedTuple

# Legacy audit logs are dated `YYYY-MM-DD-*.md` — NOT sequential ADRs. A real
# ADR is `NNNN-<slug>.md` where <slug> does not start with `MM-DD`.
_DATED = re.compile(r"^\d{4}-\d{2}-\d{2}")
_NNNN = re.compile(r"^(\d{4})-")
_CLAIM_STATUSES = {"added", "renamed"}


class PRFile(NamedTuple):
    pr_number: int
    path: str
    status: str


class ADRStateUnavailable(RuntimeError):
    """Authoritative GitHub ADR state could not be proven complete."""


def _num(name: str) -> int | None:
    """ADR number from a bare filename, or None if it isn't a numbered ADR."""
    if _DATED.match(name):
        return None
    m = _NNNN.match(name)
    return int(m.group(1)) if m else None


def _root_adr_path(path: str) -> tuple[str, str] | None:
    """Normalized root-level ADR path and filename, when applicable."""
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    if parts[:2] != ["docs", "adr"] or len(parts) != 3:
        return None
    return normalized, parts[2]


def _adr_number(path: str) -> int | None:
    """Return a root-level real ADR number, excluding dated names."""
    root_path = _root_adr_path(path)
    if root_path is None or not root_path[1].endswith(".md"):
        return None
    return _num(root_path[1])


def _is_placeholder(path: str) -> bool:
    """Whether path is exactly docs/adr/XXXX-<slug>.md."""
    root_path = _root_adr_path(path)
    if root_path is None:
        return False
    name = root_path[1]
    return name.startswith("XXXX-") and name.endswith(".md") and name != "XXXX-.md"


def _policy_paths(paths: Iterable[str]) -> tuple[dict[int, set[str]], list[str]]:
    """Return numbered and placeholder root-level ADR paths."""
    numbered: dict[int, set[str]] = {}
    placeholders = []
    for path in paths:
        root_path = _root_adr_path(path)
        if root_path is None:
            continue
        normalized, _ = root_path
        number = _adr_number(normalized)
        if number is not None:
            numbered.setdefault(number, set()).add(normalized)
        elif _is_placeholder(normalized):
            placeholders.append(normalized)
    return numbered, placeholders


def _format_policy_records(records: Iterable[tuple[int, str, int, str, str]]) -> list[str]:
    """Sort structured records and format their stable diagnostics."""
    errors = []
    for number, path, pr_number, kind, current_path in sorted(records):
        if kind == "duplicate":
            errors.append(
                f"Duplicate ADR {number:04d} in checked-out tree: {current_path}."
            )
        elif kind == "main-placeholder":
            errors.append(f"{path} is unfinalized; main may not contain ADR placeholders.")
        elif kind == "ready-placeholder":
            errors.append(
                f"{path} is unfinalized; ready PRs require numeric ADR filenames."
            )
        elif kind == "base":
            errors.append(
                f"ADR {number:04d} already exists on the base branch as {path}; "
                f"{current_path} must use a different number."
            )
        else:
            errors.append(
                f"ADR {number:04d} is also added by PR #{pr_number} as {path}; "
                "use XXXX or finalize after that claim changes."
            )
    return errors


def _tree_policy_errors(paths: Iterable[str], *, allow_placeholders: bool) -> list[str]:
    """Return deterministic duplicate/placeholder errors for one tree."""
    numbered, placeholders = _policy_paths(paths)
    records = []
    for number, matched_paths in numbered.items():
        if len(matched_paths) > 1:
            records.append(
                (number, min(matched_paths), 0, "duplicate", ", ".join(sorted(matched_paths)))
            )
    if not allow_placeholders:
        records.extend(
            (10_000, path, 0, "main-placeholder", "") for path in placeholders
        )
    return _format_policy_records(records)


def _pull_request_policy_errors(
    *,
    current_pr: int,
    draft: bool,
    current_files: Sequence[PRFile],
    base_paths: Sequence[str],
    other_files: Sequence[PRFile],
) -> list[str]:
    """Return deterministic current-vs-base/current-vs-open-PR errors."""
    current_paths = [f.path for f in current_files if f.status in _CLAIM_STATUSES]
    current_numbered, placeholders = _policy_paths(current_paths)
    records = []
    for number, matched_paths in current_numbered.items():
        if len(matched_paths) > 1:
            records.append(
                (number, min(matched_paths), 0, "duplicate", ", ".join(sorted(matched_paths)))
            )
    if not draft:
        records.extend(
            (10_000, path, 0, "ready-placeholder", "") for path in placeholders
        )

    base_by_number: dict[int, set[str]] = {}
    for path in base_paths:
        number = _adr_number(path)
        root_path = _root_adr_path(path)
        if number is not None and root_path is not None:
            base_by_number.setdefault(number, set()).add(root_path[0])

    other_by_number: dict[int, set[tuple[str, int]]] = {}
    for file in other_files:
        if file.pr_number == current_pr or file.status not in _CLAIM_STATUSES:
            continue
        number = _adr_number(file.path)
        root_path = _root_adr_path(file.path)
        if number is not None and root_path is not None:
            other_by_number.setdefault(number, set()).add((root_path[0], file.pr_number))

    for path in current_paths:
        number = _adr_number(path)
        root_path = _root_adr_path(path)
        if number is None or root_path is None:
            continue
        normalized = root_path[0]
        for base_path in sorted(base_by_number.get(number, set()) - {normalized}):
            records.append((number, base_path, 0, "base", normalized))
        for other_path, pr_number in sorted(other_by_number.get(number, set())):
            if other_path != normalized:
                records.append((number, other_path, pr_number, "open-pr", normalized))
    return _format_policy_records(records)


def _repository(*, run=None, allow_discovery: bool = False) -> str:
    """Return the GitHub owner/repository name required by REST endpoints."""
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if repository.count("/") == 1 and all(repository.split("/")):
        return repository
    if not allow_discovery:
        raise ADRStateUnavailable("GITHUB_REPOSITORY is unavailable or malformed.")
    runner = subprocess.run if run is None else run
    try:
        result = runner(
            ["gh", "repo", "view", "--json", "nameWithOwner"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        repository = json.loads(result.stdout).get("nameWithOwner", "")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise _gh_failure("repository", exc) from exc
    if repository.count("/") != 1 or any(not part for part in repository.split("/")):
        raise ADRStateUnavailable("GitHub repository discovery is malformed.")
    return repository


def _gh_failure(endpoint: str, exc: BaseException) -> ADRStateUnavailable:
    """Convert command/parse failures without exposing command response data."""
    detail = type(exc).__name__
    if isinstance(exc, subprocess.CalledProcessError):
        detail += f" (exit {exc.returncode})"
    return ADRStateUnavailable(f"GitHub state read failed for {endpoint}: {detail}.")


def _gh_object(endpoint: str, *, run=None) -> dict:
    """Read one GitHub REST object through gh api."""
    runner = subprocess.run if run is None else run
    try:
        result = runner(
            ["gh", "api", endpoint],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        data = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise _gh_failure(endpoint, exc) from exc
    if not isinstance(data, dict):
        raise ADRStateUnavailable(f"GitHub state read failed for {endpoint}: expected object.")
    return data


def _gh_pages(endpoint: str, *, run=None) -> list[dict]:
    """Flatten gh api --paginate --slurp pages after shape validation."""
    runner = subprocess.run if run is None else run
    try:
        result = runner(
            ["gh", "api", endpoint, "--paginate", "--slurp"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        pages = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise _gh_failure(endpoint, exc) from exc
    if not isinstance(pages, list):
        raise ADRStateUnavailable(f"GitHub state read failed for {endpoint}: expected pages.")
    items = []
    for page in pages:
        if not isinstance(page, list):
            raise ADRStateUnavailable(f"GitHub state read failed for {endpoint}: expected page.")
        for item in page:
            if not isinstance(item, dict):
                raise ADRStateUnavailable(f"GitHub state read failed for {endpoint}: expected item.")
            items.append(item)
    return items


def _base_paths(ref: str, *, run=None, allow_discovery: bool = False) -> list[str]:
    """Read an untruncated Git tree for the PR base SHA/ref."""
    endpoint = f"repos/{_repository(run=run, allow_discovery=allow_discovery)}/git/trees/{ref}?recursive=1"
    tree = _gh_object(endpoint, run=run)
    if tree.get("truncated") is not False:
        raise ADRStateUnavailable("GitHub base tree is truncated or malformed.")
    entries = tree.get("tree")
    if not isinstance(entries, list):
        raise ADRStateUnavailable("GitHub base tree is malformed.")
    paths = []
    for entry in entries:
        path = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(path, str):
            raise ADRStateUnavailable("GitHub base tree is malformed.")
        paths.append(path)
    return paths


def _pull_files(pr_number: int, *, run=None, allow_discovery: bool = False) -> list[PRFile]:
    """Read all changed-file pages; reject an unverifiable 3,000-file result."""
    endpoint = f"repos/{_repository(run=run, allow_discovery=allow_discovery)}/pulls/{pr_number}/files?per_page=100"
    files = _gh_pages(endpoint, run=run)
    if len(files) >= 3_000:
        raise ADRStateUnavailable("GitHub pull request file list reached the 3,000-file ceiling.")
    result = []
    for file in files:
        path, status = file.get("path"), file.get("status")
        if not isinstance(path, str) or not isinstance(status, str):
            raise ADRStateUnavailable("GitHub pull request file list is malformed.")
        result.append(PRFile(pr_number, path, status))
    return result


def _open_pull_numbers(*, run=None, allow_discovery: bool = False) -> list[int]:
    """Read every open pull-request page."""
    endpoint = f"repos/{_repository(run=run, allow_discovery=allow_discovery)}/pulls?state=open&per_page=100"
    numbers = []
    for pull in _gh_pages(endpoint, run=run):
        number = pull.get("number")
        if isinstance(number, bool) or not isinstance(number, int):
            raise ADRStateUnavailable("GitHub open pull-request list is malformed.")
        numbers.append(number)
    return numbers


def _all_open_pull_files(*, run=None, allow_discovery: bool = False) -> list[PRFile]:
    """Read every open PR's complete file collection or fail as a unit."""
    files = []
    for number in _open_pull_numbers(run=run, allow_discovery=allow_discovery):
        files.extend(_pull_files(number, run=run, allow_discovery=allow_discovery))
    return files


def _local_adr_paths(repo_root: Path) -> list[str]:
    adr_dir = repo_root / "docs" / "adr"
    return [path.relative_to(repo_root).as_posix() for path in adr_dir.glob("*.md")]


def policy_check(
    repo_root: Path,
    *,
    event_name: str,
    event: dict,
    run=None,
) -> list[str]:
    """Validate checkout plus authoritative PR/base/open-PR state."""
    local_errors = _tree_policy_errors(
        _local_adr_paths(repo_root), allow_placeholders=event_name == "pull_request"
    )
    if event_name == "push":
        return local_errors
    if event_name != "pull_request":
        raise ADRStateUnavailable(f"Unsupported CI event: {event_name!r}.")
    try:
        pull = event["pull_request"]
        number, draft, base = pull["number"], pull["draft"], pull["base"]
        base_sha = base["sha"]
    except (KeyError, TypeError) as exc:
        raise ADRStateUnavailable(f"Pull-request event is malformed: {type(exc).__name__}.") from None
    if isinstance(number, bool) or not isinstance(number, int) or not isinstance(draft, bool) or not isinstance(base_sha, str):
        raise ADRStateUnavailable("Pull-request event is malformed.")
    current_files = _pull_files(number, run=run)
    base_paths = _base_paths(base_sha, run=run)
    other_files = []
    for open_number in _open_pull_numbers(run=run):
        if open_number != number:
            other_files.extend(_pull_files(open_number, run=run))
    return local_errors + _pull_request_policy_errors(
        current_pr=number,
        draft=draft,
        current_files=current_files,
        base_paths=base_paths,
        other_files=other_files,
    )


def _local_max(adr_dir: Path) -> int:
    return max(
        (n for p in adr_dir.glob("*.md") if (n := _num(p.name)) is not None),
        default=0,
    )


_NO_GH_WARNING = (
    "warning: open-PR ADR scan did not run (no usable `gh` CLI: {why}). "
    "The number below is guarded by local files and live reservations ONLY — "
    "an ADR added by an already-open PR will NOT be seen. Verify against open "
    "PRs before use."
)


def _open_pr_max(*, strict: bool = False, run=None) -> int:
    """Max ADR number in files added by any open PR. 0 if gh is unavailable.

    Failing soft is right — the local scan still ran — but failing *silently*
    is not: the caller gets a confidently wrong number and cannot tell the
    degraded answer from the guarded one. Cloud/web sessions have no `gh` at
    all (GitHub is reached through MCP there), so this half of the scan is dark
    for a whole class of session; #454 is a live instance where it handed out a
    number an open PR already used. Warn on stderr so the degradation is
    visible to every caller, in-process or via subprocess, without changing the
    number printed on stdout.
    """
    try:
        files = _all_open_pull_files(run=run, allow_discovery=True)
    except ADRStateUnavailable as exc:
        if strict:
            raise
        why = type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__
        print(_NO_GH_WARNING.format(why=why), file=sys.stderr)
        return 0  # fail soft — local-only scan still ran
    return max((_adr_number(file.path) or 0 for file in files), default=0)


_NO_REMOTE_WARNING = (
    "warning: origin/main ADR scan did not run ({why}) -- could not verify "
    "against origin/main; number may collide with unmerged upstream ADRs, "
    "cross-check manually."
)


def _remote_max(root: Path) -> int:
    """Max ADR number on origin/main. 0 (with a stderr warning) if unverifiable.

    Local trees only show what's *checked out*; a stale tree hands out a number
    already merged upstream (#495: returned 0129 while origin/main had 0130).
    Fetch is best-effort — a stale origin/main ref is still a better floor than
    none, so a failed fetch warns but still reads the ref.
    """
    try:
        fetched = subprocess.run(
            ["git", "-C", str(root), "fetch", "--quiet", "origin", "main"],
            capture_output=True, text=True, timeout=15,
        )
        if fetched.returncode != 0:
            print(_NO_REMOTE_WARNING.format(why="fetch failed"), file=sys.stderr)
        out = subprocess.run(
            ["git", "-C", str(root), "ls-tree", "--name-only", "origin/main",
             "docs/adr/"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        print(_NO_REMOTE_WARNING.format(why=type(exc).__name__), file=sys.stderr)
        return 0  # fail soft — local + PR scans still ran
    return max(
        (n for line in out.splitlines()
         if (n := _num(Path(line).name)) is not None),
        default=0,
    )


def _scan_max(root: Path) -> int:
    """Highest ADR number in local files + open PRs + origin/main — no
    reservations, no +1."""
    return max(_local_max(root / "docs" / "adr"), _open_pr_max(),
               _remote_max(root))


def _reserved_max() -> int:
    """Highest live ADR number reserved in the coordination registry (0 if the
    registry isn't reachable — e.g. a cloud checkout with no coordination dir).
    """
    try:
        coord = Path(__file__).resolve().parents[2] / "coordination"
        sys.path.insert(0, str(coord))
        import registry  # type: ignore
        vals = registry.live_values(registry.claims_path(), "adr")
    except Exception:
        return 0  # fail soft, same as gh being unavailable
    best = 0
    for v in vals:
        try:
            best = max(best, int(v))
        except (TypeError, ValueError):
            pass
    return best


def next_adr_number(repo_root: Path | None = None) -> int:
    # This file lives at <root>/.claude/skills/new-adr/ OR
    # <root>/.agents/skills/new-adr/ — both put root at parents[3].
    root = repo_root or Path(__file__).resolve().parents[3]
    return max(_scan_max(root), _reserved_max()) + 1


def _check() -> None:
    # ponytail: the parse / max / zero-pad is the only non-trivial logic — assert it.
    assert _num("0099-foo.md") == 99
    assert _num("0105-phase4-review.md") == 105
    assert _num("0088-3d-analyst-tools.md") == 88          # slug starting w/ digit
    assert _num("README.md") is None
    assert _num("TEMPLATE.md") is None
    assert _num("2026-06-18-agent-decisions.md") is None   # dated legacy, not ADR
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        adr = Path(d) / "docs" / "adr"
        adr.mkdir(parents=True)
        for n in ("0001-a.md", "0007-b.md", "README.md", "2026-01-01-x.md"):
            (adr / n).write_text("")
        assert _local_max(adr) == 7
        assert _local_max(Path(d) / "docs" / "missing") == 0   # absent dir -> 0

    # #454: gh absent must warn, not just quietly return 0.
    import contextlib
    import io
    real_run, err = subprocess.run, io.StringIO()
    try:
        def _boom(*_a, **_k):
            raise FileNotFoundError("gh")
        subprocess.run = _boom
        with contextlib.redirect_stderr(err):
            assert _open_pr_max() == 0
    finally:
        subprocess.run = real_run
    assert "open-PR ADR scan did not run" in err.getvalue()

    # #495: git absent must warn, not silently skip the origin/main floor.
    real_run, err = subprocess.run, io.StringIO()
    try:
        def _no_git(*_a, **_k):
            raise FileNotFoundError("git")
        subprocess.run = _no_git
        with contextlib.redirect_stderr(err):
            assert _remote_max(Path(".")) == 0
    finally:
        subprocess.run = real_run
    assert "origin/main ADR scan did not run" in err.getvalue()

    print("next_adr_number self-check OK")


def main(argv=None, environ=None, run=None) -> int:
    """Run the number helper or its fail-closed CI policy check."""
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--base", action="store_true")
    modes.add_argument("--policy-check", action="store_true")
    parser.add_argument("--event-file")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[3]
    if args.check:
        _check()
        return 0
    if args.base:
        print(_scan_max(root))
        return 0
    if not args.policy_check:
        print(f"{next_adr_number():04d}")
        return 0
    env = os.environ if environ is None else environ
    event_path = args.event_file or env.get("GITHUB_EVENT_PATH")
    event_name = "pull_request" if args.event_file else env.get("GITHUB_EVENT_NAME")
    try:
        if not event_path:
            raise ADRStateUnavailable("GitHub event file is unavailable.")
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        if not isinstance(event, dict):
            raise ADRStateUnavailable("GitHub event file is malformed.")
        errors = policy_check(root, event_name=event_name, event=event, run=run)
    except ADRStateUnavailable as exc:
        print(f"ADR policy state unavailable: {exc}", file=sys.stderr)
        return 2
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ADR policy state unavailable: {type(exc).__name__}.", file=sys.stderr)
        return 2
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("ADR policy check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
