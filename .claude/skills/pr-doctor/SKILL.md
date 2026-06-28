---
name: pr-doctor
description: Diagnose a PR — reads its comments, reviews, CI checks, merge state, and any failed run logs, then explains what's blocking it. Usage: /pr-doctor [PR number]
---

# pr-doctor

Figure out why a PR is stuck, was closed, or won't merge — without the user
having to reconstruct the history.

## Steps

1. **Find the PR.** If a number was given, use it. Otherwise resolve from the
   current branch:
   ```
   gh pr list --head "$(git branch --show-current)" --state all \
     --json number,title,state --limit 1
   ```

2. **Pull the full picture:**
   ```
   gh pr view <n> --json title,state,body,mergeable,mergeStateStatus,\
baseRefName,headRefName,reviews,comments,statusCheckRollup,closedAt
   ```

3. **If CI checks failed**, get the failing run's log:
   ```
   gh run list --branch <headRefName> --limit 5 \
     --json databaseId,status,conclusion,name,workflowName
   gh run view <databaseId> --log-failed
   ```

4. **Review-thread comments** (line-level), which `pr view` may not surface:
   ```
   gh api repos/0bnoxide/AutoGIS/pulls/<n>/comments
   ```

5. **Synthesize.** State plainly what is blocking the PR — pick the real cause:
   - failing CI (quote the failing test / log line)
   - requested changes in a review (quote the ask)
   - merge conflict / `mergeable: CONFLICTING` (name the base it diverged from)
   - draft state, or simply closed without merge (say so + when)
   Then give the concrete next action. Be specific; cite the file:line, test
   name, or comment rather than summarizing vaguely.
