# ROUTE — coverage and release status

**Research package:** `OGE_1_5_ALL_STORIES_RESEARCH_V1.zip`, `STORIES/ROUTE/` (2026-11-02).
**Adapter:** `app/math/scenarios/stories/ROUTE.py`, generator `route-grid4-v1`.
**Source statement:** the five IDs below form the single complete GRID-4 bundle documented in the package. The generated prompts are authored analogues; original wording and artwork are not reproduced.

## One compatible five-question block

| Position | Implemented family | Source ID | Archived witness | Implemented computation |
|---|---|---:|---:|---|
| 1 | ROUTE-F01-GRID-MATCH | 408182 | code `213` | Read the three numbered points in the named highway order; preserve code as a string. |
| 2 | ROUTE-F03-ROAD-SUM | 408186 | `32 + 24 = 56 km` | Sum only the two consecutive highway edges on the named route. |
| 3 | ROUTE-F05-PYTHAGORAS | 408188 | `sqrt(32^2 + 24^2) = 40 km` | Exact integer hypotenuse from the same grid coordinates and cell scale. |
| 4 | ROUTE-F06-HIGHWAY-TIME | 408190 | `60 * 56 / 20 = 168 min` | Convert hours to minutes once; use the source-backed 20 km/h speed. |
| 5 | ROUTE-F09-SHOPPING-MIN | 408193 | minimum `1134 RUB` | Recompute four basket totals from the visible per-unit price table and return the unique minimum cost. |

Seed `0` is a deterministic oracle witness for the archived numeric values. Its five-row product table has two active basket rows and is a synthetic witness that produces the archived four totals; it is **not** claimed to reproduce the unavailable source table. Other seeds use one GRID-4 world, exact scaled integer geometry, a fixed source-backed highway speed, and a strict basket minimum selected from 2–4 of five product rows. Every snapshot stores all five positions against the same world and seed.

## Source diagram audit

The archive's `MANIFEST.json`, atlas and `RISKS_AND_COVERAGE.md` all say the original raster audit is incomplete. They describe a 404 from the screenshot path and confirm only catalog HTML text/solution inspection. Direct source links are recorded in the family atlas (`408182`, `408345`, `408470`), but this implementation did not obtain a usable original raster to compare node positions, crossing semantics, cell scale and edge labels. FIPI's navigator confirms the broad №1–5 practical-task area; it does not confirm this specific map.

Accordingly, the new renderer is an authored deterministic GRID-4 SVG/PNG witness, not an assertion of pixel or full-topology fidelity to an original exam diagram. All five family registrations remain `enabled=false`; the shared registry cannot issue the story. A source-raster audit is still required before any family is enabled.

## Candidate-family boundaries

- Included in the single bundle: F01, F03, F05, F06 and F09.
- F02 village-map matching and F10 fuel balance remain excluded because the package marks them `research_only` pending a seven-node source-image audit.
- F04 road subtraction, F07 direct-route time and F08 mixed-route time are not substituted into this five-question block. They belong to alternate source sets/variants, and the archive documents only one complete GRID-4 five-question set. Adding them to this block would create the cross-kit mixing the handoff forbids.
- This is a bounded implementation of one compatible source-like set, not coverage of all eight `enabled_candidate` entries or all №1–5 bank tasks.

## Independent checks

- `tests/test_route_adapter.py` exercises source vectors, `single` positions 1–5, `full`, default fail-closed status, snapshot/assets restoration and 250-seed generation/oracle QA.
- The independent verifier checks graph nodes/edge types, exact integer geometry, scale, SVG node coordinates and labels, visible edge lengths, table quantities/prices, route names, exact answers, solution equations and same-world compatibility.
- Mutation cases cover implemented graph, text, price-table, scale, geometry, speed, solution, answer, asset-digest and mixed-seed risks. Mutations for excluded candidate families are rejected by the family boundary. Stale callbacks and duplicate callback attempts remain covered by the existing scenario repository/PostgreSQL tests; no router or repository code changed.
- `scripts/oge15_route_quality_report.py --seeds 1200` completed 6,000 independent question-oracle checks. After removing whole-scene state from the fingerprint, the observed per-question unique counts are F01 503, F03 349, F05 179, F06 349, and F09 1200. F05 is below the 200-unique acceptance threshold. Fingerprints include the visible condition, question-specific math model, and answer, and exclude unrelated scene state.
- Current F05 variation is bounded by the two integer highway legs and endpoint names; 179 unique questions appeared in 1,200 seeds. Do not treat the former 1,200 count as question diversity or claim 179 exhausts the mathematical domain. Enumerate reachable leg/name combinations and decide whether a documented finite-capacity exception is justified; keep this family disabled meanwhile. Other counts exceed 200 but remain blocked by the missing original diagram audit.

## Release gate

Student access is disabled pending the original-diagram audit and a separately approved flow integration. No shared engine, migration, Telegram router, or other story adapter changed. This report does not claim full atlas or bank coverage.
