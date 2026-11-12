# ADR-0138: Compliance trend counts non-detects at half the RL and needs 4 points

**Status:** Accepted

**Date:** 2026-11-12

## Context
Before this change, `compliance_summary.compute_trend` fitted only detected values and gave a direction label from as few as 3 points (#615). A well that went from detects to all non-detects therefore had its trend fitted on the remaining detects, and a few noisy points could produce a label in the compliance workbook. #616 already made the slope unit-independent. The owner was asked how non-detects should count and how many points a trend needs.

## Decision
- The trend series includes non-detects at half the reporting limit (`ReportingLimit`, falling back to `DetectionLimit`). This matches the existing `half_rl` rule in `concentration_surface`.
- A non-detect with neither limit is left out of the trend and noted with an INFO QA record (`trend_nondetect_no_limit`). It is INFO rather than WARNING because these rows were always left out, and result files without limits must not start failing.
- A trend needs at least 4 points (`compute_trend` `min_points` and `build_compliance_summary` `min_events_for_trend` both default to 4). Fewer points give `insufficient_data`.
- Non-detects change only the trend. Detection, exceedance and maximum statistics still use detected values only.
- No significance test (such as Mann-Kendall) is added. The owner did not ask for one.

## Consequences
- Wells that go non-detect now trend `improving` instead of being judged on their old detects.
- Some 3-event series that used to get a label now show `insufficient_data`.

## Alternatives considered
- Treating non-detects as ties below the RL (Mann-Kendall style), or adding a significance test. The owner chose half the RL and a 4-point minimum.

## Related decisions
- Issue #615; unit-independent slope from PR #616
