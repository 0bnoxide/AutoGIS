# Workbook Inspection Summary — PLACEHOLDER

**Status: BLOCKED — required inputs were not provided.**

| Severity | Category | Message |
|---|---|---|
| ERROR | missing_required_input | `H281 Glasgow Data Tables thru April 2026.xlsx` was referenced by the specification but not supplied. The inspection deliverable cannot be produced; the parser profile remains DRAFT/unverified. |
| ERROR | missing_required_input | Reference figure PDF #1 (CKG groundwater analytical example) not supplied — callout symbology cannot be matched visually. |
| ERROR | missing_required_input | Reference figure PDF #2 (CKG potentiometric example) not supplied. |
| ERROR | missing_required_input | Reference figure PDF #3 (ZT42 soil analytical example) not supplied. |
| ERROR | missing_required_input | Reference figure PDF #4 (ZT42 groundwater quality example) not supplied. |

Recommended action: provide the workbook and the four reference figures,
run Tool 1 on the workbook, and replace this file with the generated
`*_inspection.json` / `.csv` outputs.

Per the project's own rules, missing inputs produce placeholders plus QA
errors — they are never silently invented.
