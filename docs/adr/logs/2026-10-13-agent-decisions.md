# Agent decisions — 2026-10-13

## Issue #558: reject unsafe R9 timestamps without changing stored keys

**Decision:** Validate separate zero-padded `MM/DD/YYYY` analysis dates and
`HH:MM` analysis times for profiles with `test_sheet`, preserving blank
discriminators. Validate every TST and RES row before joins; structural failures
abort every record append, including valid siblings. Keep shared cell codecs,
test-join/run-token recipes, schema and production keys unchanged.

**Reasoning:** Canonicalizing formerly accepted aliases would churn existing
keys. Minute codecs erase source seconds and spreadsheet decoders can round
fractions before the codec sees them. Preserve private source evidence; inspect
raw OOXML with standard-library ZIP/XML APIs and compare numeric native cells
to exact minute serialization, with no tolerance. Full-match raw ISO text so
decoder prefix matching cannot conceal fractions or timezone suffixes. Reject
unverifiable native encodings. BIFF time-origin cells remain blocking rather
than acquiring a changed text/key recipe. No runtime dependencies were added.

**Revisit if:** Real exports establish a broader source precision contract and
the owner authorizes any necessary key migration. This synthetic fix does not
close #244's WMRD rerun or existing-geodatabase gates; no real data or native GIS
qualification is claimed. XLS controls exercise real cell/loader codecs using
synthetic xlrd workbook objects, rather than a newly authored BIFF binary.

## Issues #576–#579: close independent timestamp review gaps

**Decision:** Propagate unsafe timestamp evidence to a fixed point independent
of alias order, and validate FSample contributors before any TST/RES override.
Keep source alias application and frozen join/run/key recipes unchanged. Resolve
the actual workbook part through OPC package relationships and require its
content-type declaration to agree. Follow relative worksheet part relationships;
unavailable or ambiguous source proof produces structural QA and the existing
whole-batch append abort.

**Reasoning:** Independent review showed reverse three-hop aliases and inherited
sample fields could mask precision loss. A valid relocated workbook exposed a
hardcoded package-layout assumption. The initial proof pass also retained every
worksheet cell. Use decoded header positions to select identity and alias cells,
stream worksheet XML, clear cells and detach completed rows. Retain sample proof
only when sample headers can contribute run identity. This bounds added proof
retention; the existing loader still materializes decoded row dictionaries.

**Revisit if:** Real exports justify broader timestamp or package contracts. No
tolerance, key migration, real-data/native GIS qualification or large-memory
trial is introduced. Frozen rejected attempt evidence remains immutable.

## Issue #576: validate text sources through transitive timestamp aliases

**Decision:** Reuse one reverse reachability closure for native proof capture
and per-role validation of every present raw date/time contributor. Validate
text even if alias order leaves the canonical field absent, or a canonical
value overrides the raw source. Terminate cycles through finite set closure.
Preserve actual single-pass source alias values, blank degradation and key
recipes; do not synthesize missing identity components.

**Reasoning:** Review002 showed metadata-only propagation missed unsafe plain
text aliases, allowing seconds, fractions, unpadded values and timezone suffixes
to disappear before validation. Raw text and native loss evidence must follow
the same declared role reachability. Existing structural QA and batch abort are
sufficient; no additional importer behavior or options are needed.

**Revisit if:** The owner authorizes changing value alias resolution or frozen
identity recipes. Current canonical, blank and override outputs retain their
literal baseline keys. All rejected attempt evidence remains immutable.

## Issue #580: enforce structural reader QA at the headless batch caller

**Decision:** In `run_batch_import`, record the QA position immediately before
reading each workbook. Reject that workbook before normalization or aggregation
when the new reader records contain ERROR-level `equis_invalid_run_timestamp`
or `equis_test_key_collision`. Raise through the existing per-workbook exception
handler, which emits an ERROR manifest row with zero counts and continues.

**Reasoning:** The batch API and CLI compose the reader directly and therefore
bypassed the single-import structural guard. CLI exit status alone did not stop
unsafe normalized records from reaching CSV output. Limit this guard to the
current workbook's new structural errors; existing QA and ordinary per-row
errors must preserve the existing continuation policy in Accepted ADR-0048.
Both manifest and directory input modes use the same guard. No reader, key,
profile, schema, CLI output sequencing or production GDB behavior changes.

**Revisit if:** Additional reader-level structural failure categories are
introduced. Actual headless synthetic API/CLI CSV results qualify this repair;
real exports and native GIS remain separate acceptance gates.

## Issue #581 and shared QA reuse: preserve source and import boundaries

**Decision:** Retain formula presence with the selected raw timestamp cells.
Reject absent, empty or unusable cached values before the decoded type check;
accept verified canonical caches, including numeric midnight, and genuine blanks.
Do not evaluate formulas or change codecs, aliases or key recipes. In the single
importer, record the caller QA boundary before reading. Scope structural guards,
status, final counts and persisted QA to this import. Create the consumer view
after the last producer so late append diagnostics remain included. Preserve the
original collector for every producer and the caller aggregate; retain its record
identities and order, and use the original object for a fresh collector.

**Reasoning:** Independent synthetic probes showed uncached formulas decode to
None and acquire accepted blank keys. They also showed previous timestamp errors
abort later valid imports and previous QA is replayed into the new batch. A guard
slice alone cannot fix final status, counts and persistence. Local record views
are sufficient; the existing finalizer and QA writer do not mutate the collector.
No global QA policy, schema, batch/CLI behavior or production keys need changing.

**Revisit if:** Concurrent reuse of a collector or formula freshness requires a
different contract. These sequential synthetic tests qualify cache presence and
per-import QA consumption, not formula evaluation, real exports or native GIS.
All rejected attempts and independent probe evidence remain immutable.
