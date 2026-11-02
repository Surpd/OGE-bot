# OGE task 11 coverage and release status

As of 2026-11-02, synchronized with `main` at `0c15c0b06df3b2cba913baa637aed83a40c5cc38` (PR #14).
F01–F08 passed independent catalog image review and are enabled in this branch.
See `specs/OGE11_RELEASE_AUDIT.md` for source-by-source findings.

| Family | Research status | Runtime | Text prototype IDs | Source image audit |
|---|---|---:|---|---|
| F01 | enabled | on | 339085, 349265 | all 6 original graphs reviewed; codes 123, 132 |
| F02 | enabled | on | 340583; FIPI-DEMO-2027-11 (draft) | 340583's 3 SVGs reviewed; code 132; draft image is supplementary, not visual evidence |
| F03 | enabled | on | 341702 | all 3 original graphs reviewed; code 132; `b=y(0)` |
| F04 | enabled | on | 348381 | coefficient-sign rows А/Б/В → numbered graphs 1/2/3; code 321; `c=y(0)` |
| F05 | enabled | on | 349706 | all 3 original graphs reviewed; code 132 |
| F06 | enabled | on | 350104, 350202 | supports both: graph letters→formula numbers (213) and formula letters→graph numbers (132) |
| F07 | enabled | on | 340835 | graph letters А/Б/В → formula numbers 1/2/3; code 132 |
| F08 | enabled | on | 341668 | formula letters А/Б/В → graph numbers 1/2/3; includes `1/(2x)`; code 132 |
| F09 | research_only | off | subtype of F01/F02 | not a distinct generator |
| F10 | research_only | off | 369530 | condition/solution conflict |
| F11 | blocked | off | no confirmed example | shifted root/hyperbola forms unsupported |

The listed catalog images were loaded from their original `get_file` resources
and visually reviewed in the browser. Codes were recomputed from visible graphs
and formulas, not inferred from published solutions. The FIPI-2027 example is a
draft mirrored PDF, not the final exam; its published code 132 is supplementary
metadata. `atlas/oge11_source_cases.csv` and `atlas/oge11_release_audit.json`
carry source-level records and implementation-family decisions.

## Implemented mathematical and image scope

- F01–F02: three distinct linear, quadratic and inverse graphs with independent
  orderings of the formula and graph sides.
- F03: three distinct sign pairs for `(k,b)` with graph panels А/Б/В and sign options 1/2/3.
- F04: coefficient-sign rows А/Б/В match numbered graph panels 1/2/3; `a` is checked
  by branch direction and `c` by `y(0)`, not by the vertex ordinate.
- F05–F07: slopes through the origin, general straight lines, and one constant
  horizontal function matched with two non-constant lines.
- F08: inverse-proportion graphs `y=q/x`, including `q=1/2`, drawn on separate domains around zero.
- The image is generated as a 700×1530 PNG with three stacked panels, common
  viewport `[-5,5] × [-5,5]`, axis ticks and control-point pixel checks. The
  exact PNG bytes and SHA-256 are stored in the immutable problem snapshot and
  reused on resume. It is not a static or generated illustration.
- Panel identifiers follow each prompt: F01, F04, F05, F06's formula-letter
  layout, and F08 use graph panels `1, 2, 3`; F02, F03, F06's graph-letter
  layout, and F07 use graph panels `А, Б, В`. F06 stores the chosen layout in
  each immutable snapshot. Source-by-source orientation and code fixtures are
  in `atlas/oge11_release_audit.json`.
- Answer policy `oge11.three-digit-bijection@1` accepts exactly one ASCII
  permutation of `123`; answers remain strings.

Quality numbers are in `reports/oge11-quality.json`. They cover generated
mathematical analogues, independent mathematical and pixel oracles, and the
renderer. They do not establish full exam-bank coverage. F09/F10 remain
research-only and F11 remains blocked.
