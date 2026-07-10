# Agent decisions — 2026-07-10 (WQX Step-2 import, branch feat/wqx-step2-import)

Supplement to ADR-0080, not a substitute. Autonomous judgment calls made while
building the Step-2 WQX reader ("continue with the next phase" directive).

1. **Proceeded to Step 2 without waiting for PR #223 to merge**, branching from
   `origin/main` (not stacking on the gate branch) since the reader is
   producer-side and shares no code with the consumer conversions. The gate is
   honored at merge time instead: the PR is explicitly marked mergeable only
   after #223. Rationale: stacking would add rebase churn for zero coupling.

2. **Deviated from ADR-0075's "fold ResultBasis when dual-reported" sketch** to
   an unconditional fold-when-non-empty (ADR-0080 decision 4). The conditional
   per-file scan is cross-batch key-unstable (same row, different key, dup on
   reimport). ADR-0075 itself froze only the key composition and column names,
   "not the recipe"; recorded as a refinement, decided before any real WQX row
   lands.

3. **Scoped Step 2 to the CSV serialization** despite the Step-1 program line
   naming "CSV/JSON/XML" — the paper mapping verified the CSV dictionary and a
   real USGS CSV export; JSON/XML are loader-only additions when a real need
   appears (YAGNI). Recorded in spec D1 so it reads as a decision, not an
   omission.

4. **Skipped `Rejected`-status rows at read time** (+ QA-WARN) even though no
   spec item demanded it — importing rejected results would let them reach
   screening summaries as ordinary detections; the advisor review flagged the
   silent-pollution potential and the fix is 4 lines.

5. **Ran a pre-implementation advisor pass on the spec** (continuing the
   pattern the user set on the merge gate). It caught 3 genuine blockers before
   any code existed (resolve_column no-fall-through-on-empty, sci-notation ND
   token, unmapped-condition silent IsNotAnalyzed) — all fixed in the spec, not
   in review churn later.

6. **Named this log file with a `-wqx-step2` suffix** instead of the plain
   date-only convention: PR #223 already adds
   `2026-07-10-agent-decisions.md`, and a same-path file here would guarantee a
   content conflict at rebase.
