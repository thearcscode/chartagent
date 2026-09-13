# First-ask legality — 2026-09-14

Untyped planner — after ADR-0023 Decision 4's item-key fix (#143) and #144's per-ask journal, before the typed menu (#147). Fixture and instruction set (#145) at commit `72d9e5f6e8519dc150c9b7e140b311009f36ea24`. Library commit `1e44571bae4d08757fc511af568fa3a2c203d7cd`. Model `anthropic:claude-sonnet-4-6`, temperature 0. Flint `0.5.1` / bundle `d82901aa5bf701f892e11b6e68b28cfc7ec6cd7ac8cac35bdf2e9a0248a23e06`.

There is no gate (ADR-0023 Decision 8). This is the *before* half of the after-measurement #147 will run on the same committed set.

## First-ask legality

Verdicts included: 12 of 75 (16.0%).

Verdicts excluded: 12 of 75 (16.0%).

## First step-1 attempt outcome breakdown

`decode` 0, `assemble` 63, `refuted` 0, `ok` 12.

## Repair success

Of the runs whose first step-1 attempt missed, 20 of 63 (31.7%) reached `ok` on the extra ask.

## Manifest

- Fixture/instruction commit (#145): `72d9e5f6e8519dc150c9b7e140b311009f36ea24`
- Library commit: `1e44571bae4d08757fc511af568fa3a2c203d7cd`
- Model: `anthropic:claude-sonnet-4-6`
- Flint pin: `0.5.1` / `d82901aa5bf701f892e11b6e68b28cfc7ec6cd7ac8cac35bdf2e9a0248a23e06`
