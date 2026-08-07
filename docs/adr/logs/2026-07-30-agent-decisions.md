# Agent decisions — 2026-07-30

## CI-red diagnosis: hosted-runner assignment failure, no repo change shipped

- **Decision:** Diagnosed the repo-wide instant CI failures (PRs #389/#390,
  post-merge run of #387 on `main`) as an **account-level GitHub Actions
  runner-assignment failure** — most consistent with exhausted included
  Actions minutes or the spending limit on this private repo — and
  deliberately shipped **no workflow change**. An initial windows-2022-
  retirement hypothesis was tested and discarded: a `workflow_dispatch`
  validation run on `windows-2025` and a minimal `echo` probe on
  `ubuntu-latest` both failed identically (~5 s, `runner_id: 0`, no logs,
  empty check output), so the ADR-0119 `windows-2022` pin is not the cause
  and was left untouched.
- **Reasoning:** Every failed job since 2026-07-29 ~07:00 UTC dies before a
  runner is assigned, across all hosted labels and OSes; the identical suite
  was green on `windows-2022` at 06:53 UTC the same day; githubstatus.com
  shows no ongoing Actions incident. No commit can fix exhausted minutes —
  the resolution is the account billing page (raise spending limit or wait
  for the included-minutes cycle reset). Changing the runner pin on this
  evidence would have shipped a plausible-looking wrong fix.
- **Revisit if:** CI stays red after minutes/spending are restored — then
  re-test runner labels individually before touching ADR-0119.
