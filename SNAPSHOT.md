# About this snapshot

This repository is a snapshot of the author's working repository, taken at commit `773d561fca1ca4165a00fdeb044676dab126b5af`
of that repository. Later changes are added as new commits, and each commit message names the commit of the working repository
that it reproduces. None of the history of the working repository is included.

## Contents

- The harness, its unit tests and the job definitions of the main run, as they were run.
- For each experiment used by the thesis: its scripts, inputs and result files, including the fixed prompts and evidence sheets of the
  model-assisted labeling steps (Appendix A.7 of the thesis).
- The LaTeX sources of the thesis, the macro generators and the generated macro files.

## Not included

- Raw execution records of the main run (about 65 GB). They are kept by the author and are available on request.
- Working documents of the author (planning notes, decision records, protocol drafts, literature notes and copies of papers).
- The history of the working repository.

## Notes for readers

- Comments in the code and in some result files are written in Vietnamese and refer to working documents and dates of the working
  repository. The code is kept exactly as it was run, so these references are left unchanged.
- Commit hashes that appear in comments, result files and provenance files refer to the history of the working repository.
- `experiments/41-lp-star/scripts/fetch.sh` downloads raw records from branches of the working repository and does not work from this
  snapshot; its result files (`experiments/41-lp-star/results/`) are included.
- The labels of equivalent and non-equivalent mutants used in the validation are not included (Appendix A.7 of the thesis).
