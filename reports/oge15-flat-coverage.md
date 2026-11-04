# FLAT adapter coverage

Research basis: `OGE_1_5_ALL_STORIES_RESEARCH_V1.zip`, `STORIES/FLAT/` (V1,
2026-11-02). This report describes implementation coverage of that package; it
does not claim exhaustive coverage of the OGE item bank.

| Family | Position | Status in research | Adapter state | Basis / limitation |
|---|---:|---|---|---|
| `FLAT-01-ROOM-MATCH` | 1 | enabled_candidate | Implemented, disabled | Fixed eight-room topology, graph clues, ordered four-digit answer. |
| `FLAT-02-TILE-PACK` | 2 | enabled_candidate | Implemented, disabled | Exact 0.4 m square grid, no-cut tile fit, integer ceiling by pack. |
| `FLAT-02-PARQUET-PACK` | 2 | enabled_candidate | Implemented, disabled | 4.8×5.2 m room; 0.2×0.8 m boards fit 6×26 without cutting. |
| `FLAT-03-RECT-AREA` | 3 | enabled_candidate | Implemented, disabled | Fixed 3×10-cell loggia; exact 4.8 m² control result. |
| `FLAT-04-RECT-PERCENT` | 4 | enabled_candidate | Implemented, disabled | Exact 30 vs 20 cells; denominator is the smaller storage area. |
| `FLAT-04-COMPOSITE-PERCENT` | 4 | enabled_candidate | Excluded from generation | Its only disputed positive example is 409306; rounding is unresolved. |
| `FLAT-05-WASHER-MIN` | 5 | enabled_candidate | Implemented, disabled | Six-row authored table, capacity/type/height constraints, installation and delivery included, unique minimum required. |
| `FLAT-05-INTERNET-MIN` | 5 | enabled_candidate | Implemented, disabled | Two capped plans plus unlimited plan; exact `Fraction` overage cost and unique minimum. |
| `FLAT-ALT-TOPOLOGY` | 1 | research_only | Excluded | Alternative plan grid is not verified. |
| `FLAT-02-CUTTING-WASTE` | 2 | blocked | Excluded | Cutting and waste rules are not specified by verified examples. |

Seven of the eight candidate structures are generated. The eighth remains
registered but cannot be selected; every family has `enabled=False`. The single
research-only and blocked structures also remain non-generating. Thus the
adapter is installed for engineering review, while OGE 1–5 remain unavailable
to students through the fail-closed registry.

## Control block

The deterministic seed `20220523` reconstructs the supplied five-card control
answers `1346`, `12`, `4.8`, `50`, `950` from one immutable plan. Cards
424898–424902 are catalog-attributed and text/answer checked in the research
package; this branch does not represent them as independently verified FIPI
originals. No source PNG is used.

## Geometry and assets

Room polygons and door locations use integer 0.4 m cells. The apartment floor
is checked as a complete, non-overlapping cell partition; balcony cells are
checked separately. Labels, door graph, scale, areas, visible conditions,
tiling orientation, costs and answers are checked independently. SVG and PNG
are produced from the model and restored from the immutable snapshot; their
SHA-256 digests are recorded in `oge15-flat-quality.json`.

See [the QA report](oge15-flat-quality.json) for the 300-seed run, observed
fingerprint count, control vector comparison and asset digests.
