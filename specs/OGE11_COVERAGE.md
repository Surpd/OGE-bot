# OGE task 11 coverage and release status

As of 2026-11-02, branch base `faf25fd23ad141c9ba0a83948e525cec9115cb12`.
F01–F08 passed independent catalog image review and are enabled in this branch.
See `specs/OGE11_RELEASE_AUDIT.md` for source-by-source findings.

| Family | Research status | Runtime | Text prototype IDs | Source image audit |
|---|---|---:|---|---|
| F01 | enabled | on | 339085, 349265 | all 6 original graphs reviewed; codes 123, 132 |
| F02 | enabled | on | 340583; FIPI-DEMO-2027-11 (draft) | 340583's 3 SVGs reviewed; code 132; draft image is supplementary, not visual evidence |
| F03 | enabled | on | 341702 | all 3 original graphs reviewed; code 132; `b=y(0)` |
| F04 | enabled | on | 348381 | all 3 original graphs reviewed; code 321; published explanation misstates `c` |
| F05 | enabled | on | 349706 | all 3 original graphs reviewed; code 132 |
| F06 | enabled | on | 350104, 350202 | all 6 original graphs reviewed; codes 213, 132 |
| F07 | enabled | on | 340835 | all 3 original graphs reviewed; code 132 |
| F08 | enabled | on | 341668 | all 3 original graphs reviewed; code 132 |
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
- F03–F04: three distinct sign pairs for `(k,b)` or `(a,c)`; `c` is checked as
  `y(0)`, not as the parabola's vertex ordinate.
- F05–F07: slopes through the origin, general straight lines, and one constant
  horizontal function matched with two non-constant lines.
- F08: inverse-proportion graphs `y=q/x`, drawn on separate domains around zero.
- The image is generated as a 700×1530 PNG with three stacked panels, common
  viewport `[-5,5] × [-5,5]`, axis ticks and control-point pixel checks. The
  exact PNG bytes and SHA-256 are stored in the immutable problem snapshot and
  reused on resume. It is not a static or generated illustration.
- Panel identifiers follow each condition's two sides: F01 and F05–F08 show
  graph panels `1, 2, 3` while formulas are `А, Б, В`; F02–F04 show graph
  panels `А, Б, В` while formula/sign options are `1, 2, 3`. This convention
  was checked against reviewed source wording and graph images.
- Answer policy `oge11.three-digit-bijection@1` accepts exactly one ASCII
  permutation of `123`; answers remain strings.

Quality numbers are in `reports/oge11-quality.json`. They cover generated
mathematical analogues, independent mathematical and pixel oracles, and the
renderer. They do not establish full exam-bank coverage. F09/F10 remain
research-only and F11 remains blocked.
