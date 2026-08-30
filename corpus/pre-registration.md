# corpus-prereg-v1 authoring note

**Date:** 2026-08-30.

This note is the dated companion to `corpus/pre-registration.json`.
The tag `corpus-prereg-v1` is cut on the commit that adds these bytes.
No planner prompt is committed before that tag.

## What was authored

Fifty requests and five reserves. Each request pins one dataset by
sha256, carries a shape label, and has a façade-valid reference frame —
or a null frame with `expressible_if` for the four cell-1 slots.
The freeze schema has no reason field (ADR-0014 appendix). The stated
reason is the cell-1 intent plus `expressible_if`: r31/r32 nothing in
the 48 encodes membership overlap (Venn/Euler/UpSet); r33 no simplex
geometry (Ternary); r34 Map and Choropleth place values, flow lines
are a layer (Flow Map).

The cell × stratum matrix is 22/0/4/2/2 and 0/4/6/4/6. Shape marginals
are common-path 12/12/3/3 and adversarial 4/6/4/6. The nine carryable
intents are floored at one each on the common-path 30. Designed
common-path counts: trend 7, comparison 9, distribution 1,
correlation 2, part-to-whole 6, ranking 2, flow 1, geographic 1,
single-value 1.

Cell-2 common-path slots are spreadsheet-wide one-row extracts of the
nvBench aggregate, then UNPIVOT (r23 ranks, r24 male-guest years,
r25 hall-of-fame years, r26 assistant-professor sexes). The menu
cannot melt those columns. Adversarial cell 2 keeps UNION ALL,
strptime, window, PIVOT … IN, and conditional aggregation. The
reserve for common-path cell 2 is UNION ALL.

r09 keeps nvBench's wording ("how old is each student and how many
students are each age?"). The gold vis is one Age-by-count chart, not
a cell-4(iii) compound ask. r22 is the single-value floor: Bullet of
room_count against bedroom_count, both columns already on Apartments.

## Sources

nvBench 1.0's unnamed-mark subset is the ID and dataset spine for the
common-path 30. Fluency rewrites do not add or remove a measure, a
grain, a filter, or a chart-type name. Both versions are stored.
nvBench gold vis, `chart`, and any `steps` reasoning are not the
reference frame.

Cell-4(ii) is three authored sentences (degrees 2, 2, and 4). nvBench
2.0 is not used. NLV Corpus is a register reference only. Quda is not
used.

## Reserves

Five reserves, keyed on `(cell, stratum)`, draw order 1–5:
common-path cell 0, common-path cell 2, adversarial cell 1,
adversarial cell 3, adversarial cell 4. Substitution is a lookup.
Dropping is the fallback when reserves are exhausted, and only for
unscoreability discovered before a run.

## Pin

Authoring pin: Flint `0.5.1` / fixture `34ef451`.
