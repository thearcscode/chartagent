# eval-benchmark-v1 authoring note

**Date:** 2026-10-11.

This note is the dated companion to `eval/pre-registration.json`. The tag
`eval-benchmark-v1` is cut on the commit that holds these bytes. The rules are
ADR-0029; this note records what was authored under them. `tools/score_eval.py`
was not touched.

## What was authored

The public 150 combine three partial files, now consumed and not part of the
freeze: 102 nvBench 1.0 common-path cases (90 cell-0, 12 cell-2; ids `nv001`
onward), 14 authored cases (4 cell-1, 2 cell-3 silent row-drop, 8 adversarial
cell-2; ids `auth-*`) and 34 authored cell-4 cases (ids `c4-*`).
`tools/author_eval_freeze.py` assembled them. It is a one-shot script, not a
library surface, and re-running it after the tag is a freeze break.

The cell x stratum matrix is 90/0/12/2/16 common-path and 0/4/8/0/18
adversarial. Shape marginals are 48/48/12/12 common-path and 6/9/6/9
adversarial. The common-path intent counts are 28/36/4/8/24/8/4/4/4. The
cell-4 family table is (i) 0/8, (ii) 10/2, (iii) 4/4, (iv) 2/4. No request is
an unanswerable instruction, an injection case or Excel-named. nvBench source
ids are disjoint from `corpus-prereg-v1`, and no dataset byte string is reused
from `corpus/data/`.

The hold-out pool is 30 authored cases (`ho-01` to `ho-30`, disjoint from the
public ids): common 24 and adversarial 6, cells 15/0/3/1/5 and 0/1/2/0/3. It
holds one cell-1, one row-drop, and cell-4 cases from all four families
(common (ii), (ii), (iii), (iv), (iv); adversarial (i), (ii), (iii)). It has
no designed nine-intent table. Its tables are pinned under `eval/data/holdout-*`.

The 30 smoke ids are cell-0 18 (two per intent), cell-1 1, cell-2 4 (two
common-path, two adversarial), cell-3 1 and cell-4 6 (three common-path, three
adversarial, one per family drawn). Smoke ids, the hold-out permutation and the
human-calibration permutation come from recorded seeds (the `seeds` field),
chosen before any run existed. The human-calibration permutation covers
exactly the public 150; the hold-out permutation covers exactly the pool.

`flint_version` 0.5.1 and `fixture_commit` 34ef451 match
`corpus-prereg-v1`. Cell-1 `expected_outcome` is the rail reading (miss,
bucket 1); the era reading is the gate's, not a stored field.

## The 95% budget, in both eras

**Before the custom-rail seam is in the wheel:** six authored executable misses
are designed in: four cell-1 raises and the two cell-3 row-drops. At n=150,
143/150 = 95.3% clears 95% and 142/150 = 94.7% does not, so one discretionary
miss remains. Cell-4 is not a designed miss, only if the planner escapes.

**Now that the seam (ADR-0030, `generate_recipe`) is in the wheel:** the four
cell-1 cases are expected custom-rail executable hits, not misses. The designed
budget is the two row-drops alone, which leaves five discretionary misses before
the point estimate falls under 95% (143/150).

The stored `expected_outcome` does not change between eras and the tag is not
edited; n stays 150 either way. The gate owns the era reading.

## Licences

See `eval/NOTICE`. nvBench query text is MIT; tables extracted from nvBench
databases descend from Spider (CC BY-SA 4.0) and share-alike applies to those
files only. Authored requests and tables are Apache-2.0. Quda, NLV and
nvBench 2.0 are not vendored.

## Known gaps

No injection-suite request list is committed anywhere in the repository, so the
injection-suite disjointness check ran against an empty instrument. Nothing in
the freeze is an injection case; the check becomes real when that suite exists.
