# Callout placement overrides

Edit the `Env_CalloutPlacementOverrides` table inside the GDB (or load
`example_overrides.csv` into it), then re-run Tool 4. Fields:

| Field | Meaning |
|---|---|
| SiteID / FigureSpecID / MapType / EventDate | Scope of the override |
| LocationID | The callout to override |
| AnchorX, AnchorY | Lower-left corner of the box in map units. If set, the box goes exactly here. |
| OffsetX, OffsetY | Optional nudge added to AnchorX/Y. |
| PreferredQuadrant | NE/NW/SE/SW/E/W/N/S — tried FIRST when no anchor is set. |
| LockedPlacement | 1 = never moved by the collision engine, even if it overlaps. 0 = used as the first candidate but may be moved on collision. |

Typical loop: run Tool 4 -> review COLLISION_WARNING boxes in the QA report
-> set anchors for those wells -> re-run Tool 4 (replace_existing on).
