# mining on vouch — from fork to shipped

vouch pays open contributors to make its retrieval engine better, scored
by a benchmark anyone can reproduce on any machine. no wallet, no subnet,
no tarball uploads: your mining rig is a fork and a text editor, and the
scoreboard is a github workflow.

the thing you submit is **code** — a ranking strategy the benchmark runs
in a sandbox. and the prize is bigger than the payout: a winning strategy
that passes review ships as the default in the next release. your ranking
code runs on every vouch install.

## the loop, end to end

```bash
# 1. fork + clone, then:
pip install -e '.[dev]'

# 2. see where the money is — the zeros are the levers
vouch bench run --seeds 1,2,3,4,5,6

# 3. start from the worked example
cp contrib/strategies/example_lexical.py contrib/strategies/<you>.py

# 4. practice locally with the EXACT scoring loop CI uses —
#    same sandbox, same paired seeds, same margin math
vouch bench run --seeds 1,2,3,4,5,6 \
    --strategy contrib/strategies/<you>.py \
    --against contrib/strategies/baseline.py

# 5. when it says DETHRONED, open a PR touching only your strategy file
```

the `koth-engine-gate` workflow scores your PR against the reigning
champion over the day's seeds and posts the full scorecard as a comment.
win or hold, you see exactly why.

## what a strategy is

one function, data in, order out:

```python
from vouch.strategy import Candidate

def rank(query: str, candidates: list[Candidate], *, limit: int) -> list[str]:
    ...  # return candidate ids, best first
```

a `Candidate` is `kind`, `id`, `summary`, `score` — data only. the
sandbox blocks network, subprocesses, and file writes; ordering is
authoritative but bounded (invented ids are ignored, omitted candidates
are appended). see `docs/koth-strategy-lane.md` for the full contract and
sandbox details.

## how you get paid

* **daily throne (provisional).** the scorecard names the day's champion;
  days-on-throne accrue between dethrones.
* **monthly season (settled).** a sealed commit-reveal run on seeds that
  did not exist before the cutoff settles the standings; rank shares are
  65/14/10/7/4 (`docs/vouchbench-seasons.md`). payouts go through a
  PR-native bounty platform or github sponsors within a week.
* **flat bounties.** issues labeled `bounty:$X` pay on merge for
  benchmark hardening, new categories, and adapters — that ladder is how
  the benchmark itself keeps improving.
* **the ledger** lives in `competition/LEADERBOARD.md`; every scorecard's
  inputs (seeds, commit, command) are public, so any row can be
  recomputed by anyone.

## the merge rule

**highest verified score merges.** engine code never auto-merges: the
sandbox stops code from cheating the scorer, and pre-merge human review
stops code that overfits the benchmark — lookup tables, category-pattern
dispatch, generator-template matching are the disqualifiers
(`docs/vouchbench-seasons.md`). review is a veto for cheating, never a
taste test. a clean win merges, ships in the next release, and is
credited in the changelog. on merge, the ledger sweep promotes the
winner to reigning champion automatically — the merge threshold ratchets
up with every merged win, because the next challenger is scored against
you.

## warming up: the kit lane

not ready to write ranking code? the kit ladder
(`docs/koth-ladder.md`) is the 10-minute on-ramp: PR a change to one
bounded yaml file of retrieval knobs and the same paired scorer runs. it
auto-merges on a win because data cannot execute. treat it as the
tutorial — its ceiling is low by construction (most single knobs cannot
move the bench), and the real levers, the benchmark's zero-score
categories, are only reachable from code.

## why trust the scores

no TEE, no oracle: the score is a pure function of (seed, code). seeds
derive from the champion sha and the utc date; season seeds come from
public drand randomness at the cutoff. every scorecard can be recomputed
offline with one command. reproducibility is the whole trust model.
