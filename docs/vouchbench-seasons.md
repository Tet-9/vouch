# VouchBench Seasons — competition rules

A recurring, cash-bountied competition to improve vouch's retrieval engine,
scored by `vouch bench` — a seeded, judge-free benchmark whose score is a
pure function of (seed, code). Anyone can reproduce any score on any
machine; that reproducibility is the whole trust model.

## How a season runs

1. **Open.** A season issue announces: the pinned bench contract, the public
   practice seeds, the bounty pool and split, and `main`'s current
   per-category scores (the zeros are the levers — that table is the map of
   where the money is).
2. **Enter.** An entry is a pull request labeled `season-N`. Every push gets
   practice scores from CI automatically (the `vouchbench-season` workflow's
   pull_request path — public seeds, instant feedback).
3. **Freeze.** At the announced cutoff timestamp, the last commit on each
   entry is that entry. Pushing after the cutoff voids the entry for the
   season (next season it can re-enter).
4. **Score.** A maintainer dispatches the scored run. The scored seeds are
   derived from the public drand randomness round at the cutoff time and
   recorded in the season issue — they did not exist while entries could
   still change, so nothing can be pre-fit to them (commit-reveal). Every
   entry and `main` run the same seeds; results are paired.
5. **Review.** Ranked entries get normal code review before any payout.
   Grounds for disqualification: benchmark-keyed logic (lookup tables,
   category-pattern dispatch, generator-template matching), bypassing the
   review gate, or violating the repo's non-negotiables (no write path
   around `proposals.approve()`, plaintext storage, no baked model deps).
   Near-identical entries: the earlier-opened PR wins (first-seen).
6. **Pay and merge.** Every entry that beats `main`'s composite by the
   margin band — `max(0.007, 1.96 x SE_paired)` over the scored seeds —
   earns its rank share of the pool (65 / 14 / 10 / 7 / 4 while the field
   is small). The winner merges and becomes the champion the next season
   must dethrone.

## Two ladders

* **Ladder A — the score race** above.
* **Ladder B — flat bounties**: issues labeled `bounty:$X` for benchmark
  hardening (new categories, better generators, anti-overfit work),
  adapters, and bug fixes. Paid on merge after review. Ladder B is how the
  benchmark itself keeps improving.

## Payment

Payouts go through a PR-native bounty platform (Polar.sh / Algora) or a
GitHub Sponsors one-time payment, at the maintainer's choice, within a week
of the season closing. The maintainer's decision on scores, bands, and
disqualifications is final; every input needed to re-derive a score
(seeds, commit, command) is public in the season issue.

## Local loop for contributors

```bash
pip install -e '.[dev]'
vouch bench run --seeds 1,2,3,4,5,6        # the public practice baseline
vouch bench gen --seed 1                   # inspect a dataset + answer key
vouch bench run --seed 1 --json            # full report with failures
```

The reference baseline and the current lever table live in
`src/vouch/bench.py`'s module docstring.
