# Survey123 submission provenance

`autogis envmon trace-survey123` compares a Survey123 device SQLite export
with a hosted feature layer and, optionally, a client's downstream layer.
It writes per-record evidence and distinct counts for progress review.

**DRAFT:** implemented and tested headlessly against synthetic SQLite exports
and simulated feature services. Acceptance on a sanitized real device export
and a non-production organization remains pending. Issue [#414](https://github.com/0bnoxide/AutoGIS/issues/414)
was explicitly authorized for implementation by the owner on 2026-09-12;
this does not open Survey123 Phases 4–7 or close other acceptance gates.

## Offline use

The base install is sufficient. Copy the device database after closing the
field app; keep the original intact. Do not copy just the SQLite main file
while its data remains in a WAL/journal. Consolidate the export first using
the field application's supported recovery process. Active WAL/journal
sidecars are checked before and after reading and rejected; the reader opens
SQLite with `mode=ro&immutable=1`, a read
transaction, `query_only=ON`, and `trusted_schema=OFF`. Before/after SHA-256
checks reject a main file that changes during the read. Immutable mode prevents
SQLite from creating WAL/shared-memory sidecars beside the source. It also
disables SQLite's locking and change detection, so a closed, consolidated
export that no other process changes is required; never point this command
at the live field-app database. See [SQLite read-only WAL guidance](https://sqlite.org/wal.html#read_only_databases).

The supported schema is `Surveys(name, data, status)`, with `data` containing
a JSON object keyed by the form's root table name. Select that **exact root**
with `--device-root`; unrelated forms are excluded and counted. `name` is
not assumed to be a reliable form identifier. If different surveys reuse a
root name, supply a separately isolated, consolidated export containing only
the intended form; repeating the command against a mixed export cannot
separate those forms. Use separate invocations for schemas requiring different
identity fields. An unmatched root, malformed
JSON, unsupported status, or incompatible schema fails the command.

```powershell
python -m autogis envmon trace-survey123 `
  --device C:/exports/crew-a.sqlite --device C:/exports/crew-b.sqlite `
  --device-root inspection --device-key globalid `
  --hosted-json C:/exports/hosted.snapshot.json --hosted-key GlobalID `
  --client-json C:/exports/client.snapshot.json --client-key OriginalGlobalID `
  --out C:/reports/provenance-2026-09-12
```

Omit `--client-json` when the client cannot be observed. The report records
the client as unobserved (`null` counts), not an empty layer. `--out` must
not exist. A completed report is published as one directory; retries use a
new directory. No device, hosted service, client service, or sync checkpoint
is modified. Standard CLI run history records the invocation and outcome.

### Saved snapshot contract

Each saved JSON input represents **one complete layer**, not an incremental
`sync-survey123` JSONL stream, arbitrary feature list, or a single REST page:

```json
{
  "version": 1,
  "complete": true,
  "source": "https://services.example.org/arcgis/rest/services/inspections/FeatureServer/0",
  "observed_at": "2026-09-12T16:00:00+00:00",
  "features": [
    {"attributes": {"GlobalID": "{12345678-1234-1234-ABCD-123456789ABC}"}}
  ]
}
```

The exporter/operator must verify completeness before asserting
`complete: true`, record the actual observation time with its timezone,
and identify the layer or saved dataset in `source`. An empty complete
snapshot (`features: []`) is valid. The reader cannot independently prove
an offline exporter's assertion. Missing or false completeness, wrong
version/shape, missing timezone, and a transfer-limit flag are refused.
Use a source label such as `export:inspection-2026-09-12` for local data.
HTTP source URLs must be credential-free HTTPS layer URLs.

## Live read-only use

```powershell
pip install "autogis[survey123]"
python -m autogis envmon trace-survey123 `
  --device C:/exports/crew-a.sqlite --device-root inspection `
  --hosted-url https://services.example.org/arcgis/rest/services/inspections/FeatureServer/0 `
  --profile organization --hosted-key GlobalID `
  --client-url https://client.example.org/arcgis/rest/services/inspections/FeatureServer/2 `
  --client-key OriginalGlobalID --client-profile client `
  --out C:/reports/provenance-live-2026-09-12
```

Each live leg has its own profile; omit that profile for anonymous/public
access. Credentials stay in the existing ArcGIS profile/keyring provider.
URLs containing credentials, query parameters, or fragments are refused
before run-history recording. Raw provider errors are suppressed because
they can contain tokens. An authorization/network failure aborts the run;
it is never interpreted as an empty endpoint.

The pull requests all features (`where=1=1`, `return_all_records=True`) and
compares their OBJECTIDs with inventories taken before and after the query.
An incomplete or changing inventory aborts the run. The source access scope
may still hide records through sharing, view filters, or permissions. This
is not a transaction across servers: edits to existing records during the
pull and differences in observation time remain limitations. Editor
tracking is not required for a client view. Attachment downloads, repeats,
publishing, and writes to services are outside this command.

## Identity and evidence

Choose a stable field that retains the **same meaning across all three
legs**. Prefer GlobalID and a client's preserved original GlobalID; use
explicit business-key fields if the forwarding process changes GlobalIDs.
Never join by OBJECTID across layers. The command does not infer a key
crosswalk from names, geometry, row order, or similar-looking IDs.

UUID strings normalize case and brace/hyphen representation. Other strings
remain case-sensitive and exact. Integer identifiers become decimal text;
null, bool, float, container, blank, whitespace-padded, and control-character
identifiers are invalid. Missing IDs remain separate review records;
duplicate IDs preserve every observation and become `needs_review`.
Supplying the same device path twice is rejected. Repeating an export under
a different filename still produces duplicate findings, not additional
new-work counts.

`provenance.json` contains input file hashes and paths, snapshot source/time,
key fields, device row references/status/edit mode, per-feature payload hashes,
the observations behind each match, and limitations. Raw form attributes,
geometry, attachments, and login credentials are not copied into the report.
Stable IDs and device paths can still be sensitive: share the report only
with the intended project participants. Hashes support evidence inspection;
they are not digital signatures or independent delivery receipts. A payload
hash can differ across legs because forwarding transforms attributes; hash
equality is not required for an identity match.

| Status | What the observations establish |
|---|---|
| `visible_at_client` | The identity exists in both hosted and client snapshots. Check device evidence separately. |
| `hosted_not_visible_at_client` | Hosted presence, no matching identity in the observed client snapshot. Cause unproven. |
| `hosted_client_not_checked` | Hosted presence; no client snapshot supplied. |
| `device_only` | Device evidence with no hosted/client match. A local Sent state is not independent delivery proof. |
| `client_only` | Client presence without matching hosted evidence, whether or not device evidence exists. |
| `needs_review` | Duplicate/invalid identity or unknown device edit mode; evidence is retained and excluded from new-ready totals. |

The report never labels endpoint absence as a confirmed QA hold. A client
record without a device copy is retained, but does not count as crew work
captured by the supplied exports. A row's stage flags do not establish that
the currently edited payload itself has been delivered.

## Counts and exit codes

`records.csv` provides per-identity statuses and row counts. Formula-like IDs
are escaped for spreadsheet display; JSON retains their exact values.
`counts.csv` lists the same summary metrics as the JSON report:

- `device_rows`, `hosted_rows`, `client_rows`: observed rows, before identity
  deduplication; inbox rows are separately reported as `excluded_inbox_rows`.
- `device_unique`, `hosted_unique`, `client_unique`: distinct valid identities
  observed per leg, including identities with duplicate findings.
- `device_new_ready_unique`: unambiguous device identities whose status is
  Outbox (1), Sent (2), or Submission Error (3), and whose `__meta__.editMode`
  is explicitly 0 (new record). Draft (0), Inbox (4), editMode 1 (update),
  unknown edit mode, and any identity ambiguity are excluded.
- `device_new_ready_hosted_unique` and `device_new_ready_client_unique`:
  subsets of that eligible device population observed at the respective leg.
  These count records, not submission attempts, repeats, photos, hours, or money.
- Status counts and `needs_review`: findings requiring reconciliation.

These are review inputs for progress billing, not approved billable quantities.
Outbox and Submission Error rows can represent completed field work even
when delivery is outstanding; the separate hosted/client totals expose that.

Exit **0** means no discrepancies under the supplied observations; **2**
means a report was written with discrepancies or review items; **1** means
input/access/output failure. CLI argument errors also use Click's standard
exit 2, but do not create a report. Finding exits are recorded as successful
tool executions in run history, with their nonzero exit noted.

## Format evidence and acceptance

- [Esri: recover a survey from a SQLite database](https://support.esri.com/en-us/knowledge-base/how-to-creating-a-replicate-survey-from-sqlite-database-000031759)
  documents `Surveys(name,data,status)` and box states.
- [The recovery script linked by Esri](https://github.com/tedrick/ReadS123DB/blob/master/readDb.py)
  demonstrates root-keyed JSON, `__meta__.editMode`, and nested repeats.
  The tracer never adopts the recovery script's generated-ID fallback.
- [FeatureLayer.query](https://developers.arcgis.com/python/latest/api-reference/arcgis.features.toc.html#arcgis.features.FeatureLayer.query)
  and [REST layer queries](https://developers.arcgis.com/rest/services-reference/enterprise/query-feature-service-layer/)
  document full-feature and ID-only query options. Checked 2026-09-12.

Before production acceptance, run a sanitized real device export against
non-production hosted/client services. Independently verify selected form,
box states, new/update metadata, preserved keys, duplicates, pagination,
sharing scope, complete counts, and before/after device hashes. Save the
report and owner sign-off; the documented shape alone is not acceptance
evidence for every field-app version.
