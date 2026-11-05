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
| `FLAT-05-WASHER-MIN` | 5 | enabled_candidate | Implemented, disabled by default | [Source №409311](https://math-oge.sdamgia.ru/problem?id=409311) asks for vertical load, capacity ≥6 kg, and minimum full price including hookup and delivery. The generator now uses those eligibility conditions and independently totals purchase price, hookup, and percent delivery. Its six-row authored table retains explicit dimensions, but no width/depth/height fit rule is applied because the prompt states none. |
| `FLAT-05-INTERNET-MIN` | 5 | enabled_candidate | Implemented, disabled | Two capped plans plus unlimited plan; exact `Fraction` overage cost and unique minimum. |
| `FLAT-ALT-TOPOLOGY` | 1 | research_only | Excluded | Alternative plan grid is not verified. |
| `FLAT-02-CUTTING-WASTE` | 2 | blocked | Excluded | Cutting and waste rules are not specified by verified examples. |

Seven of the eight candidate structures are generated for public selection. The
washer generator remains registered for research but cannot be selected; every
family still has `enabled=False` by default. The single
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

The 300-seed run produced 300 distinct observable full kits. Per-family visible
question uniqueness is separate: F01 269; F02 parquet 4 (161 samples); F02 tile
5 (139); F03 rectangle area 1; F04 rectangle percent 1; F05 internet 6 (155);
F05 washer 1 (145). These observed counts use the visible condition and answer;
they do not turn fixed geometry into extra variants. F03, F04, and washer F05 are
content-fixed under the current model. The different full kits derive from
variable room labels and data elsewhere in the shared plan and do not increase
those individual question counts. See [the QA report](oge15-flat-quality.json)
for the control vector comparison and exact asset digests.


## V2 source correction — 2026-11-05

The counts and asset digests above describe the legacy flat-grid-1.0.0 model.
The current flat-grid-2.1.0 plan uses the original 33×18-cell outline from
[424898](https://math-oge.sdamgia.ru/problem?id=424898) and its diagram
[get_file?id=90064](https://math-oge.sdamgia.ru/get_file?id=90064).
Kitchen, bedroom, corridor and door connections now agree with the picture.
The source solution's claim of a pantry→bedroom passage contradicts the drawing;
we use the drawing and the unambiguous shared wording (the bedroom is next to
the pantry), without inventing that passage. Loggias contain 30 and 44 cells;
[424900](https://math-oge.sdamgia.ru/problem?id=424900) therefore requires
selecting the smaller. Bathroom/pantry areas (30/20 cells) are read from the
plan for [424901](https://math-oge.sdamgia.ru/problem?id=424901), not given in
the question. Parquet likewise requires measuring the living room (12×13 cells).
Labels vary; geometry does not. New full-kit counts must not be presented as
new geometries. A legacy snapshot fixture checks the static SVG digest; the frozen c2570e9
PNG renderer separately verifies byte-identical restoration in the same Pillow
runtime, avoiding an invalid Windows-wheel/Linux-wheel digest comparison.
