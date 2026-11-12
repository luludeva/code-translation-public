# A Differential Testing Harness for Assessing the Validity of Reported Pass/Fail Decisions in LLM-Based C-to-Rust Translation

Code, experiment scripts and result files of the graduation thesis (University of Engineering and Technology, VNU Hanoi).
Every number reported in the thesis is computed by the scripts in `writing/scripts/` from the result files in `experiments/`.

## Layout

| Path | Content |
|---|---|
| `harness/` | The differential testing harness (Section 3.3 of the thesis): builds, execution lanes, comparison, evidence rules, records, metrics |
| `tests/` | Unit tests of the harness |
| `ci/make-shard-jobs.py` | Job definitions of the main run |
| `experiments/<nn>-<name>/` | Scripts (`scripts/`), inputs (`data/`) and result files (`results/`) of each experiment |
| `writing/` | LaTeX sources of the thesis, the macro generators (`scripts/`) and the generated macro files (`generated/`) |

## Experiments used by the thesis

| Experiment | Used for |
|---|---|
| `02-harvest-repro` | Reading and reproducing the published decisions of executables |
| `06-library-census` | Reading and reproducing the published decisions of libraries |
| `09-bnu-rules` | Classification rules of retained divergences (Appendix B) |
| `12-stderr-audit` | Normalization of standard error |
| `30-main-s0` | Main run: RQ1, RQ2 and RQ3 (Chapter 4) |
| `31-r9-check`, `32-robustness-s0`, `34-rq2-check` | Inspection of samples, case-design labels, second compiler (Section 4.1, Table 5.1, Appendix A.7) |
| `33-nonrep-evidence` | Causes of non-reproduced decisions |
| `36-heldout` | Held-out check of the harness |
| `37-rq2-san-supp`, `38-rq2-san-bound` | Rejections whose C program could not be built with sanitizers |
| `39-prereg-backfill` | Check of the input domain |
| `40-review-counts` | Parts of the observation and concentration over cases |
| `41-lp-star` | Acceptances without a result that already have a retained divergence (upper end of RQ3) |

## Reproducing the reported numbers

Requirements: Python 3.11 or later, and TeX Live with XeLaTeX and latexmk.

```
./reproduce.sh
```

The script regenerates the macro files in `writing/generated/` from the result files and builds `writing/main.pdf`.
`writing/generated/setup-numbers.tex` (environment, validation checks, calibration and operation of the main run) is kept as generated, because its inputs are raw execution records that are not part of this repository.

## Pinned external artifacts

- TRACTOR Public Test Corpus: `DARPA-TRACTOR-Program/PUBLIC-Test-Corpus`, commit `37960ee08a7c644ee66e29855eca33903f702e67`
- Published translations and decisions: `UW-HARVEST/harvest-agentic-translate-results`, commit `38352c21068c8ebcf58457ee246cd97feefeea86`

Running the harness itself requires clones of both repositories at these commits, Clang, Rust, AFL++ and the sanitizer runtimes (versions in Appendix A.1 of the thesis).

See `SNAPSHOT.md` for what this repository does and does not contain.
