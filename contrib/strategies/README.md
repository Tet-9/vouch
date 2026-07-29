# contrib/strategies - the engine-submission lane

this is the ditto-equivalent lane: you submit **real ranking code**, not a
config file. a strategy decides the order the reader sees retrieved
candidates in - the place where a new fusion, a learned reranker, or a novel
signal actually lives.

## the contract

your file exposes a `rank` function (or a `STRATEGY` object with a `.rank`
method):

```python
from vouch.strategy import Candidate

def rank(query: str, candidates: list[Candidate], *, limit: int) -> list[str]:
    # return candidate ids, best first
    ...
```

- a `Candidate` has `kind`, `id`, `summary`, `score` - **data only**. your
  code never gets the KB, the filesystem, or the network.
- ordering is authoritative but bounded: ids you invent are ignored, and any
  candidate you omit is appended in its original order. you can reorder and
  de-prioritise; you cannot fabricate or hide a result.
- [`baseline.py`](./baseline.py) is the reigning champion (returns the
  backend order unchanged). [`example_lexical.py`](./example_lexical.py) is a
  worked example you can study and beat.

## how it is scored

open a PR that touches **only** your new file under `contrib/strategies/`.
the `koth-engine-gate` workflow:

1. runs your code in a locked-down `python -I` sandbox (resource limits + an
   audit hook that blocks network, subprocess, and filesystem writes);
2. scores vouchbench with your strategy vs the reigning champion, paired over
   the day's seeds;
3. posts the scorecard and updates the engine leaderboard on a win.

## the one hard rule: engine code is never auto-merged

the config (kit) lane auto-merges because a kit cannot execute. **strategy
code can**, and vouch is a library people install - so a winning strategy is
never merged automatically. it earns the leaderboard place and the payout,
and ships only after a human reviews the code and merges it as a new default.
that human review is vouch's version of ditto's tee-plus-deployment gate: the
benchmark decides the *rank*, a person decides what *ships*.

reproduce any score locally:

```bash
pip install -e .
python .github/scripts/score_strategy.py \
  --champion contrib/strategies/baseline.py \
  --challenger contrib/strategies/example_lexical.py \
  --base-sha "$(git rev-parse origin/main)" --date "$(date -u +%F)"
```
