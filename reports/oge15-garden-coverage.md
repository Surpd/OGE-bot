# GARDEN adapter coverage and QA

Research source: `OGE_1_5_ALL_STORIES_RESEARCH_V1.zip`, `STORIES/GARDEN/`.
This adapter implements the visually checked complete Sosnovka block only.
It does not claim comprehensive coverage of OGE plot tasks.

| Family | Research state | Sources | Adapter state |
|---|---|---|---|
| GARDEN-01-IDENTIFY | candidate | 408405, 366577 | enabled for Sosnovka fixture |
| GARDEN-02-TILES-PACKS | candidate | 408413, 366578 | enabled for Sosnovka fixture |
| GARDEN-03-AREA-BUILDING | candidate | 366579, 408428, 408429 | disabled; not part of selected full block |
| GARDEN-04-PERIMETER-POLYGON | candidate | 408424 | enabled for Sosnovka fixture |
| GARDEN-05-DISTANCE-ORTHOGONAL | candidate | 408425 | disabled; no compatible verified full block |
| GARDEN-06-DISTANCE-DIAGONAL | candidate | 366581 | disabled; Avdeevo plan not visually rechecked |
| GARDEN-07-PERCENT-BUILDINGS | candidate | 408432 | enabled for Sosnovka fixture |
| GARDEN-08-PERCENT-GREENHOUSE | candidate | 408433 | disabled; no compatible verified full block |
| GARDEN-09-HEAT-BREAKEVEN | candidate | 408438, 366582 | enabled for Sosnovka fixture |
| GARDEN-10-PAINT-CHEAPEST | research_only | 408450 | disabled; not confirmed as position 5 |
| GARDEN-11-OPEN-SOIL | blocked | 408430 | blocked due to conflicting published key |
| GARDEN-12-PERCENT-AREA-DIFF | research_only | no separately verified task ID | disabled |

## Verified block

Fixture `SOSNOVKA-2025-1.1`, seed 0, yields ordered source answers
`7425 / 7 / 36 / 29 / 500` for IDs 408405 / 408413 / 408424 / 408432 / 408438.
All five positions share one immutable world snapshot and one SVG asset.
The generated plan uses a 30×20 m plot, 2 m visible grid cells, and 1 m paths;
rendered scale, object labels, house polygon area/perimeter, greenhouse nesting,
answer text, and asset restoration are checked by the adapter oracle and tests.

## QA

`python scripts/oge15_garden_quality.py` checks 250 deterministic seeds. The
current artifact `reports/oge15-garden-quality.json` records 235 unique full
conditions, at least 200 required, and zero oracle/restoration failures. The
pytest suite includes fixed source vectors, single/full snapshot identity,
blocked-family status, answer mutations, graphic movement/scale/path-width/label
mutations, and exact image restoration.

Passing generated QA does not promote unverified families or establish full bank coverage.
