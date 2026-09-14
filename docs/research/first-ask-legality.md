# First-ask legality — 2026-09-14

Whether **Planner step 1**'s first ask emits a legal fragment, before any repair
(ADR-0023 Decision 8). **Prompted, not enforced.** There is no gate. This is not
rail share and is not a re-score of `corpus-prereg-v1`.

Same instruction set (#145) at commit `72d9e5f6e8519dc150c9b7e140b311009f36ea24`.
Same model `anthropic:claude-sonnet-4-6`, temperature 0. Flint `0.5.1` / bundle
`d82901aa5bf701f892e11b6e68b28cfc7ec6cd7ac8cac35bdf2e9a0248a23e06`. 25 instructions
× 3 runs = 75 first step-1 attempts. Verdicts included and excluded match on both
halves (every `ok` was a fragment).

## Before the typed menu

Untyped planner, after the item-key fix (#143) and the per-ask journal (#144),
before #147. Library commit `1e44571bae4d08757fc511af568fa3a2c203d7cd`.

| | |
| --- | --- |
| First-ask legality (verdicts included) | **12 of 75 (16.0%)** |
| First-ask legality (verdicts excluded) | **12 of 75 (16.0%)** |
| First step-1 breakdown | `decode` 0, `assemble` 63, `refuted` 0, `ok` 12 |
| Repair success | 20 of 63 (31.7%) reached `ok` on the extra ask |

## After the typed menu (#147)

Typed menu on `main`. Library commit `8e7ca5069b8090512e5156f7c8dee90ca50d6cb7`.
Journal: `build/first_ask/journal-after-147.jsonl` (gitignored).

| | |
| --- | --- |
| First-ask legality (verdicts included) | **74 of 75 (98.7%)** |
| First-ask legality (verdicts excluded) | **74 of 75 (98.7%)** |
| First step-1 breakdown | `decode` 0, `assemble` 1, `refuted` 0, `ok` 74 |
| Repair success | 1 of 1 (100.0%) reached `ok` on the extra ask |

The one first-ask miss is **fa24** run 2: a running-total window. The first emit
used `raw_sql` with `FROM orders`. The library only allows the relation name
`source`. The extra ask repaired it.

Misses did not shift from `assemble` to `decode`. The model started emitting a
legal `transform` on the first ask. The after-rate is above the baseline, so
ADR-0023's follow-up grilling on leftover prompt lines does not open. The typed
menu is not reverted.

## Manifest

- Fixture/instruction commit (#145): `72d9e5f6e8519dc150c9b7e140b311009f36ea24`
- Before library commit: `1e44571bae4d08757fc511af568fa3a2c203d7cd`
- After library commit: `8e7ca5069b8090512e5156f7c8dee90ca50d6cb7`
- Model: `anthropic:claude-sonnet-4-6`
- Flint pin: `0.5.1` / `d82901aa5bf701f892e11b6e68b28cfc7ec6cd7ac8cac35bdf2e9a0248a23e06`
