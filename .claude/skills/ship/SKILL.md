---
name: ship
description: Run tests, push the current branch, and open a draft PR against main. Usage: /ship [optional PR title]
---

# ship

Take the current branch from "code written" to "draft PR open", with a test gate.

## Sequence

1. **Test gate.** Run `python -m pytest -q --tb=short`. If anything fails, STOP
   and report the failures. Do not push a red branch.

2. **Refuse to ship `main`.** Run `git branch --show-current`. If it is `main`,
   STOP and tell the user to create a feature branch first.

3. **Push.** `git push -u origin HEAD`.

4. **Derive the PR title** (unless the user passed one as the argument) from the
   branch name, following this repo's convention:
   - `feat/foo-bar`      â†’ `feat(envmon): foo bar`
   - `feature/foo-bar`   â†’ `feat(envmon): foo bar`
   - `worktree-foo-bar`  â†’ `feat: foo bar`
   - `docs/foo`          â†’ `docs: foo`
   - anything else       â†’ humanize the branch name
   Look at recent merged PRs (`gh pr list --state merged --limit 5`) to match the
   prevailing scope/prefix style if unsure.

5. **Open the draft PR:**
   ```
   gh pr create --base main --draft --title "<title>" --body "$(cat <<'EOF'
## Summary
<one or two lines on what changed and why>

## Failure-mode preflight

| Probe | Result | Evidence |
|---|---|---|
| `BOUNDARY_SHAPE` | PASS / FAIL / N/A | <adversarial command/test or N/A reason> |
| `CONTRACT_REACHABILITY` | PASS / FAIL / N/A | <adversarial command/test or N/A reason> |
| `IDENTITY_PROVENANCE` | PASS / FAIL / N/A | <adversarial command/test or N/A reason> |
| `SIDE_EFFECT_SAFETY` | PASS / FAIL / N/A | <adversarial command/test or N/A reason> |
| `ENVIRONMENT_SEAM` | PASS / FAIL / N/A | <adversarial command/test or N/A reason> |

## Test plan
- [ ] `python -m pytest -q` passes
- [ ] Manually verified via CLI or the .pyt toolbox (if applicable)

ðŸ¤– Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
   ```
   Fill the Summary from the branch's commits (`git log main..HEAD --oneline`).
   Classify every failure-mode probe exactly once. Applicable probes require a
   minimal adversarial command or regression test at the real call-site seam;
   `N/A` requires a concrete reason. A green full suite alone is not probe
   evidence. The table may remain incomplete while the PR is a draft, but must
   be complete before it is marked ready.

6. Report the PR URL. Mention it was opened as a **draft** â€” mark ready with
   `gh pr ready <n>` when satisfied.
