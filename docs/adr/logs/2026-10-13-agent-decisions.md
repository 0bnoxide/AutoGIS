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
