# OGE task 11 coverage and release status

As of 2026-11-02, branch base `4cc5631bb5d1f35dc8f957b3ab47a1215784e7b9`.
The implementation is a development candidate. No task-11 family is enabled for students.

| Family | Research status | Runtime | Text prototype IDs | Source image audit |
|---|---|---:|---|---|
| F01 | enabled_candidate | off | 339085, 349265 | not independently verified |
| F02 | enabled_candidate | off | FIPI-DEMO-2027-11 (draft), 340583 | source page SVG unavailable to audit; demo is a project mirror |
| F03 | enabled_candidate | off | 341702 | not independently verified |
| F04 | enabled_candidate | off | 348381 | not independently verified; published solution confuses c with vertex ordinate |
| F05 | enabled_candidate | off | 349706 | not independently verified |
| F06 | enabled_candidate | off | 350104, 350202 | not independently verified |
| F07 | enabled_candidate | off | 340835 | not independently verified |
| F08 | enabled_candidate | off | 341668 | not independently verified |
| F09 | research_only | off | subtype of F01/F02 | not a distinct generator |
| F10 | research_only | off | 369530 | condition/solution conflict |
| F11 | blocked | off | no confirmed example | shifted root/hyperbola forms unsupported |

The visible text and mathematical type were re-read for representative catalog
examples. The portal's embedded SVG images were not returned by the available
read-only viewer, so no catalog graph image or published graph code is marked
independently verified. The FIPI-2027 example is a draft mirrored PDF, not the
final 2027 exam. `atlas/oge11_source_cases.csv` carries the source-level matrix.

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
- Answer policy `oge11.three-digit-bijection@1` accepts exactly one ASCII
  permutation of `123`; answers remain strings.

Quality numbers are in `reports/oge11-quality.json`. They cover generated
mathematical analogues and the renderer's own pixel landmarks, not original
catalog image authenticity or full exam-bank coverage. F09/F10/F11 are not
generated for students. Publication needs a separate image/source audit and
runtime approval.
