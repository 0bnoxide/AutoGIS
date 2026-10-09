# 2026-10-08 — agent decisions

## Issue #449: owner-directed reserved analyte settings

- **Decision (user-directed):** The owner chose "Mark the four settings as
  inactive/reserved; preserve the schema and current output (recommended)."
  Document `significant_figures`, `nondetect_display_rule`, `result_format_rule`,
  and `default_screening_level` once in the analyte dictionary header; retain
  every key/value and the existing regulatory-value warning and `_TODO` markers.
- **Reasoning:** These settings are not consulted by current tools. The change
  clarifies their status without changing rendering, screening, or validation.
  This records the owner's choice, not an autonomous architectural decision.
- **Revisit if:** The owner authorizes implementation of any reserved setting
  with an explicit behavior contract and acceptance checks.
