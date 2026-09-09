# Agent decision log — 2026-09-09

## Issue #465 partial resolution (items 2, 4, 6) — session question-743f61

- **Scoped the PR to items 2, 4 and 6 only.** Per the 2026-08-11 re-audit
  comment on #465: item 3 shipped via #452/#453 (Sonar enforces the coverage
  gate; a pytest-side `--cov-fail-under` floor measured locally would not match
  the CI environment and risks false-red — left out deliberately), item 1 is
  not reproducible in-repo (`.codex/` was never tracked; whether to track it is
  an owner call), and item 5 (real version + first tag) is an explicit owner
  decision the issue itself flags. Items 1 and 5 stay open on #465.
- **Item 2 fix uses `--git-common-dir`, not `--show-toplevel`**, per the
  re-audit caveat: the session-start indexer must resolve the canonical main
  checkout from inside a worktree, or each worktree would register as a
  separate codebase-memory project. Verified from a live worktree that the
  derivation reproduces the previously hardcoded `repo_path`/project-key pair.
- **Item 6 hook is a 9-line `sh` script** refusing commits on `main`; enabled
  locally (`git config core.hooksPath .githooks`) and documented as a one-time
  line in README's Development section, since git config is not cloneable.
  A missing `.githooks/` in old checkouts is silently skipped by git (fail-open).
- **No ADR**: no architecture changed; #465 and its re-audit comment are the
  durable record, this log covers the judgment calls above.
