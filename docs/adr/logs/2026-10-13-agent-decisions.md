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
