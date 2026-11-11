# Agent decisions — 2026-11-10

## MSL source selection and evidence
**Decision:** Follow owner-approved archive-first/explicit-project behavior. Never infer artifact Z units from inventory original-delivery fields or a sibling raster product.
**Reasoning:** Live archive and ImageServer coverage differ; original and distributed coordinate metadata differ. Publisher accuracy fields need original labels and report links, not guessed confidence levels.
**Revisit if:** MSL publishes artifact-specific normalization/accuracy evidence or the service achieves verified equivalent coverage.

## Processing and native acceptance
**Decision:** Headless processing uses bounded raster windows; native adapter shares reference gates and records unavailable overlap statistics as unknown. Native acceptance is evaluated using real ArcPy, not inferred from mocks.
**Reasoning:** Initial sandboxed ArcPy imports could not initialize the product license; authorized desktop execution resolved this without changing license or account settings. Real native processing tests subsequently passed.
**Revisit if:** Interactive Pro selection/map checks expose a difference from scripted native processing.

## Isolated development
**Decision:** Native worktree creation reported unavailable, so use repository-required .claude/worktrees fallback with local claims. Initial implementation was kept unpublished pending owner authorization.
**Reasoning:** Owner requested implementation, not publication. Source acquisition research and test artifacts stay in the isolated ignored workspace.
**Revisit if:** Owner authorizes publication or further source-data communication.

## Publication and coverage verification
**Decision:** Publish a ready-for-review PR after explicit owner authorization, without merging. Include optional MSL dependencies in the existing Windows CI job and add adapter contract tests rather than weaken the coverage gate.
**Reasoning:** Initial hosted CI exposed a test dependency assumption, corrected without production changes. The next run passed tests but measured 66.3% new-code coverage: the raster module was skipped without its optional backend, and native adapter branches lacked offline regression coverage. Real ArcPy QA does not feed hosted coverage or establish interactive UI acceptance.
**Revisit if:** Hosted coverage still fails, independent review finds ineffective assertions, or interactive Pro acceptance exposes a difference. [PR #612](https://github.com/0bnoxide/AutoGIS/pull/612) records current checks.
