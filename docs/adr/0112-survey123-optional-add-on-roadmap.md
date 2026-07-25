# ADR-0112: Survey123 optional add-on roadmap

**Status:** Accepted

**Date:** 2026-07-25

## Context

AutoGIS already generates Survey123 XLSForms, plans sampling events, normalizes
exported submissions, routes them into local geodatabases, and reconciles field
samples with laboratory results. It does not yet manage the hosted Survey123
lifecycle: client compatibility, schema drift, incremental live reads, repeats
and attachments, controlled publication, webhooks, or feature reports.

The live operations need the ArcGIS API for Python, while the existing form and
file-processing tools do not. Making that dependency part of the base install
would weaken the arcpy/arcgis-free import boundary and charge every user for an
integration they may never use. A separately versioned plugin would add
discovery, compatibility, release, and testing machinery before an independent
package boundary has been demonstrated.

The accepted post-catalog production roadmap remains authoritative for the core
production sequence. Survey123 expansion therefore needs an explicit optional
track that neither reorders nor blocks those phases.

## Decision

1. Adopt `docs/survey123-add-on-roadmap.md` as an accepted optional roadmap with
   eight sequential phases (0–7) and four milestones. Publishing the plan does
   not start implementation; phase starts or fast-tracking remain explicit user
   decisions.
2. Keep the add-on in the existing `autogis` distribution. Introduce
   `autogis[survey123]` with the first live portal command, using the ArcGIS API
   for Python dependency already carried by `autogis[cloud]`. Keep the `cloud`
   extra working for compatibility.
3. Keep XLSForm generation, static form/schema validation, exported-file
   normalization, and offline reconciliation in the base install. Require the
   extra only for live hosted-layer, publishing, webhook-management, and
   feature-report operations.
4. Keep all commands discoverable when the extra is absent. Live commands must
   fail before network activity with the exact
   `pip install "autogis[survey123]"` remediation.
5. Preserve the arcpy/arcgis-free import invariant. Pure contracts and rules
   belong in core; authentication and hosted-service access stay behind lazy
   adapter/session seams. ArcPy remains limited to explicit local-GDB work.
6. Validate and prove the read path before adding write-side publication.
   Schema changes are classified before mutation; destructive changes require
   separate approval and rollback documentation.
7. AutoGIS will process and replay webhook payloads but will not host an
   always-running webhook service, scheduler, notification platform, or secret
   store.

## Consequences

### Positive consequences

- The default install stays lean and retains its current import boundaries.
- Existing Survey123 tools remain useful without portal credentials or the
  ArcGIS API for Python.
- The first live release is read-only and idempotent, reducing production risk
  before publication or webhook writes are introduced.
- One distribution, CLI, run history, QA system, and release process continue
  to serve the whole suite.
- Phase and milestone gates make optional work visible without changing the
  core production sequence.

### Negative consequences

- The `survey123` and `cloud` extras overlap until a broader dependency policy
  makes one alias unnecessary.
- Some commands are visible in a base install that cannot execute their live
  path until the add-on is installed.
- Live exit gates need a non-production ArcGIS organization and cannot be
  certified by the ordinary arcpy-free suite.
- Client compatibility and hosted schema behavior must be rechecked as Esri's
  Survey123 clients and APIs evolve.

## Alternatives considered

1. **Bundle the ArcGIS API for Python in the base install.** Rejected because
   static form and file workflows do not need it and the existing optional
   dependency boundary already works.
2. **Create a separate `autogis-survey123` distribution.** Rejected as premature
   packaging and compatibility machinery. Revisit only if the add-on needs an
   independent release cadence or third-party extensions.
3. **Put every Survey123 tool behind the extra.** Rejected because XLSForm
   generation, validation, normalization, and offline reconciliation are pure
   workflows that should remain available in the base install.
4. **Build a webhook server into AutoGIS.** Rejected because deployment,
   availability, scheduling, notification delivery, and secret management are
   separate operational products.
5. **Publish before implementing live reads.** Rejected because read-only
   synchronization and schema-drift evidence are prerequisites for safe
   write-side lifecycle management.

## Related decisions

- [ADR-0002: Core/adapters arcpy-free invariant](0002-arcpy-free-core-invariant.md)
- [ADR-0021: Survey123 XLSForm builder](0021-survey123-xlsform-builder-headless-openpyxl.md)
- [ADR-0045: Survey123 sampling-event planner](0045-create-sampling-event-headless-planner.md)
- [ADR-0087: Post-catalog production roadmap](0087-post-catalog-production-roadmap.md)
- [Survey123 optional add-on roadmap](../survey123-add-on-roadmap.md)
