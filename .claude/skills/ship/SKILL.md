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

## Test plan
- [ ] `python -m pytest -q` passes
- [ ] Manually verified via CLI or the .pyt toolbox (if applicable)

ðŸ¤– Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
   ```
   Fill the Summary from the branch's commits (`git log main..HEAD --oneline`).

6. Report the PR URL. Mention it was opened as a **draft** â€” mark ready with
   `gh pr ready <n>` when satisfied.
