# koth ladder — throne history

every row is a dethrone: a challenger (kit or engine strategy) that beat
the reigning champion by the margin band and landed on the ladder branch.
the merged PR is the authoritative record; this file is the human-readable
ledger, appended automatically by the `koth-ledger` workflow from the
gate's scorecard when a win lands (a maintainer can also run
`.github/scripts/update_leaderboard.py` by hand).

the daily throne is provisional (public seeds — see docs/koth-ladder.md);
payout rank is settled by the monthly sealed commit-reveal run.

| # | champion | PR | dethroned on | scored mean | margin over prior |
|---|----------|----|--------------|-------------|-------------------|
| 0 | baseline kit (repo defaults) | — | 2026-07-28 | 0.52 ± 0.03 (seeds 1–6) | — |
| 1 | plind-junior (kit) | #566 | 2026-07-27 | 0.5333 | +0.3333 |
| 2 | plind-junior (kit) | #565 | 2026-07-27 | 0.5667 | +0.3667 |
| 3 | plind-junior (engine) | #574 | 2026-07-28 | 0.7000 | +0.0375 |

payouts follow the season shares in docs/vouchbench-seasons.md
(65/14/10/7/4). days-on-throne accrue between dethrones; the monthly
commit-reveal scored run settles the season standings.
