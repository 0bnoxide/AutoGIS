---
name: new-issue
description: Create a well-structured GitHub issue from the current conversation context. Usage: /new-issue <title>
disable-model-invocation: true
---

# new-issue

Turn something discovered in the current session (a bug, a follow-up, a feature)
into a GitHub issue that matches this project's conventions.

## Steps

1. **Gather context** from the conversation:
   - the problem or feature, in one or two sentences
   - relevant tool numbers (Tool 2.x / 4.x …), ADR references, module/file names
   - reproduction steps and expected-vs-actual, if it's a bug
   - relevant code locations as `path:line`

2. **Compose the body** with these sections (drop ones that don't apply):
   ```
   ## Problem / Goal
   ## Expected behavior
   ## Reproduction (if a bug)
   ## Relevant code
   - `autogis/core/envmon/<file>.py:<line>`
   ## ADR / context refs
   ```

3. **Create it:**
   ```
   gh issue create --title "<args>" --body "<composed body>"
   ```
   Add `--label <label>` only if the user names one — don't invent labels that
   may not exist in the repo.

4. Report the issue URL.
