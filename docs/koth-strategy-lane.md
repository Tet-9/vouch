# the engine lane - submit ranking code, not config

**this is the main competition.** (new? start with the walkthrough in
[mining-on-vouch.md](./mining-on-vouch.md).) the kit ladder
(docs/koth-ladder.md) is the warm-up lane for tuning coefficients; this
lane is the ditto-equivalent: contributors submit **real engine code** -
a retrieval strategy that decides the order the reader sees candidates in -
and the benchmark scores it. it is the place a new fusion, a learned reranker,
or a novel signal actually competes. practice locally with the exact CI
scoring loop:

```bash
vouch bench run --seeds 1,2,3,4,5,6 \
    --strategy contrib/strategies/mine.py \
    --against contrib/strategies/baseline.py
```

## why a second lane exists

a kit can only move dials that already exist, so its ceiling is low - most
single knobs are no-ops on the current bench. real gains come from new ranking
logic. ditto accepts exactly this (miners submit the retrieval harness). the
difference is that ditto is a hosted service scored in a tee, while vouch is a
library people install - so the two lanes draw the trust boundary in different
places:

| | kit lane | engine lane |
|---|---|---|
| what you submit | `competition/kits/current/kit.yaml` (data) | `contrib/strategies/<name>.py` (code) |
| scored by | vouchbench, config arm | vouchbench, sandboxed strategy arm |
| on a win | **auto-merges** (data cannot execute) | leaderboard + payout; **never auto-merges** |
| how it ships | promoted to defaults by a human PR | reviewed and merged by a human |

## the interface

```python
from vouch.strategy import Candidate

def rank(query: str, candidates: list[Candidate], *, limit: int) -> list[str]:
    # return candidate ids, best first
    ...
```

a `Candidate` is `kind`, `id`, `summary`, `score` - **data only**. the
strategy never receives the KB, the filesystem, or a socket. ordering is
authoritative but bounded (ids you invent are ignored; candidates you omit are
appended). with a strategy active, retrieval over-fetches a bounded candidate
pool and the top `limit` of your order survive the cut - so de-prioritising a
candidate below the window genuinely excludes it from the pack. a strategy
still cannot fabricate a result or shrink the pack. see
`contrib/strategies/baseline.py` (the champion) and `example_lexical.py` (a
worked example).

## how a submission is scored

open a PR touching only your new `contrib/strategies/<name>.py`. the
`koth-engine-gate` workflow runs your code through
`vouch.strategy.run_sandboxed` and scores vouchbench with it, paired against
the reigning champion over the day's seeds, then posts the scorecard.

### the sandbox

each `rank` call runs in a fresh `python -I` child that, before importing your
file, installs:

- **resource limits** (`RLIMIT_CPU`, `RLIMIT_AS`, `RLIMIT_NOFILE`) and a
  parent-side wall-clock timeout - a runaway or memory-hungry strategy is
  killed, not the run;
- **an audit hook** (`sys.addaudithook`) that refuses network
  (`socket.*`/`urllib.*`), process spawning (`subprocess`, `os.exec`/`fork`,
  native `ctypes.dlopen`), and filesystem writes (any `open` with write
  intent). reads are allowed so numpy and friends still import.

a crash, a timeout, or a blocked call yields "no reordering" - a broken
strategy simply fails to improve; it cannot take down scoring.

### the honest boundary

an in-process python guard cannot stop a determined native-code escape. it is
defence in depth, not the trust root. the real boundary is the same one ditto
relies on: the scoring job runs on an ephemeral CI runner with a **read-only
token and no secrets**, and **engine code is never auto-merged**. the benchmark
decides the *rank*; a human reviewing the diff decides what *ships*. if you
ever score submissions off ephemeral CI, add OS-level isolation (a container,
nsjail, or gVisor) before trusting the audit hook alone.

## reproduce locally

```bash
pip install -e .
python .github/scripts/score_strategy.py \
  --champion contrib/strategies/baseline.py \
  --challenger contrib/strategies/example_lexical.py \
  --base-sha "$(git rev-parse origin/main)" --date "$(date -u +%F)"
```

## shipping a winner (maintainer)

1. read the strategy code - it is about to run on every user's machine.
2. move it into `src/vouch/strategies/` and point `retrieval.strategy` (a
   dotted import path) at it in the starter config, or wire it as the default.
   the in-engine hook loads a shipped strategy in-process (no sandbox - it is
   now trusted, reviewed code).
3. record the dethrone in the engine ladder's `LEADERBOARD`.

the config knob `retrieval.strategy` is how a merged strategy actually changes
retrieval; until one is merged it is unset and retrieval is byte-identical to
today.
