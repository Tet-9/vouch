# the kit ladder — the 10-minute warm-up lane

> **start here instead: [mining-on-vouch.md](./mining-on-vouch.md).**
> the main competition is the engine lane
> ([koth-strategy-lane.md](./koth-strategy-lane.md)) — contributors
> submit ranking *code* and the best verified strategy ships as the
> default. this kit ladder is the on-ramp: the same paired scorer over a
> bounded yaml file, useful for learning the loop, but its ceiling is
> low by construction — most single knobs cannot move the bench.

ditto onboards contributors by letting miners tweak a retrieval starter
kit, scoring the result, and paying whoever holds the throne. the vouch
ladder is the same loop rebuilt on github primitives — no wallet, no
subnet, no tarball uploads. your mining rig is a fork and a text editor.

## the loop

1. **fork the repo** and edit exactly one file:
   [`competition/kits/current/kit.yaml`](../competition/kits/current/kit.yaml)
   — the reigning retrieval kit. it is the whole retrieval config of the
   benchmark kb: backend, result limit, recency half-life, prompt-gate,
   rerank, and pages-first knobs, all bounded by a strict allowlist
   (`.github/scripts/validate_kit.py`). it is pure data — a kit carries
   no code.
2. **open a PR** that touches only that file, **against the ladder
   branch** (see setup below). the `koth-gate` workflow classifies it as
   a ladder entry, validates your kit, and runs vouchbench across the
   day's seeds — reigning kit vs yours, paired on identical generated
   sessions (common random numbers).
3. **dethrone** if your mean improvement clears the band
   `max(0.007, 1.96 x paired SE)`. the gate posts the full scorecard as a
   PR comment either way.
4. **auto-merge on the ladder branch.** on a dethrone against the ladder
   branch the workflow enables github auto-merge; once required checks
   are green your PR lands with no human in the loop. your kit is now the
   champion every later challenger must beat, and the merge commit is
   your permanent, public receipt.
5. **earn.** days-on-throne accrue until someone dethrones you. the daily
   ladder is provisional (see "why the daily throne is only practice");
   seasons close monthly with a sealed commit-reveal scored run
   (docs/vouchbench-seasons.md), and that is what settles payouts
   (shares 65/14/10/7/4). the ledger lives in `competition/LEADERBOARD.md`.

## reproduce any score locally

```bash
pip install -e .
python .github/scripts/koth_score.py \
  --champion competition/kits/current/kit.yaml \
  --challenger my-kit.yaml \
  --base-sha "$(git rev-parse origin/main)" \
  --date "$(date -u +%F)"
```

seeds derive from the champion sha and the utc date, so every scorecard
in ci can be recomputed by anyone — pass the same `--date` the run used
(it is printed in the scorecard) to reproduce a past result exactly. no
judge model, no hidden eval set, no api key.

## why the daily throne is only practice

the daily seeds are a deterministic function of public inputs (the base
sha and the utc date), and the whole scorer is offline-reproducible — by
design, so anyone can audit a score. the cost is that a contributor can
grid-search the knob space against today's exact seeds and submit only a
kit that already wins. the daily ladder therefore behaves like a public
practice leaderboard: fast, transparent, and overfittable.

that is fine, because **money is never tied to the daily throne.** payout
rank is decided by the monthly season's scored run, whose seeds come from
a commit-reveal drand round at the cutoff and do not exist until entries
are frozen (docs/vouchbench-seasons.md). the daily loop is where you
iterate and get instant feedback; the sealed monthly run is where a kit
has to generalise to seeds nobody could tune against.

the band (`max(0.007, 1.96 x paired SE)`) still matters daily: it stops a
kit that merely ties the champion from taking the throne, and the 0.007
floor holds the line when a deterministic overfit collapses the SE toward
zero.

## why only a data file auto-merges, and only on the ladder branch

the review gate is vouch's load-bearing invariant, and it stays load
bearing here in two ways:

- **code never auto-merges.** the ladder surface is a schema-validated
  config fragment; the worst a malicious entry can do is score badly. a
  merged ladder PR provably contains exactly one bounded data file.
- **the trunk is never auto-written.** auto-merge fires only for PRs
  whose base is the dedicated ladder branch (repo variable
  `KOTH_LADDER_BASE`). a kit-only PR opened against `main` is scored and
  commented, then a human merges — so a beatable benchmark is never the
  sole gate to code that users install. promoting the reigning kit into
  the shipped starter-config defaults is a periodic, human-reviewed PR.

engine improvements — new retrieval stages, new signals, bench
extensions — are welcome as normal PRs with human review, and the
maintainer may then expose a new knob in the kit allowlist so the ladder
can tune it. that is the division of labour: humans review capabilities,
the ladder optimises coefficients. miners on ditto never write to ditto's
core either — they submit kits that a validator scores. same boundary,
expressed as a path allowlist and a branch boundary instead of a tarball
contract.

## strategy_params — the champion family as kit surface

the largest instance of that division: the reigning engine-lane
champion's decision points are exposed as bounded data under
`retrieval.strategy_params` (schema in
`src/vouch/strategies/configured.py`, defaults = the promoted champion's
exact constants). a kit can tune the suspect penalties, the
relevance-scaled danger factor, the update boosts, the conflict-collapse
threshold, or switch whole rules off:

```yaml
retrieval:
  backend: auto
  strategy_params:
    suspect_penalty: 3.5
    danger_scale: 6.0
    conflict_collapse: false
```

the kit validator delegates this subtree to the same pydantic schema the
runtime builds the strategy from — one schema, two callers, so the gate
and the engine cannot disagree about what a legal kit is. unknown keys
and out-of-bounds values reject the kit before scoring; the dotted code
hook (`retrieval.strategy`) is deliberately NOT kit surface, because
naming code to import is not data. a winning strategy *idea* still
enters through the human-reviewed engine lane once; every configuration
of it thereafter competes — and auto-merges — as data.

## anti-cheat, mapped from ditto

| threat | ditto's answer | the ladder's answer |
|---|---|---|
| overfitting the eval | hidden benchmark versions | conceded for the daily ladder (public seeds) — it is explicitly practice; the monthly settlement uses commit-reveal seeds that do not exist until cutoff, so the paying rank cannot be pre-fit |
| lookup tables | ast minhash scan | impossible by construction: kits carry no code |
| self-reported scores | tee-locked validator | scoring runs from base-branch code under `pull_request_target`; a PR cannot alter the grader, the workflow, or the seeds it is scored with |
| copy the champion + epsilon | first-seen protection | the band forces a real margin over the reigning kit, and a tie loses to the throne |
| oversized / empty kit | — | the fetch refuses any file not returned as a small inlined blob, and the validator rejects an empty or non-`retrieval` kit, so "empty" can never be scored as champion defaults |
| stale wins racing a new champion | — | branch protection in strict mode on the ladder branch: a dethrone that lands invalidates every open challenger's check until it rebases and re-scores against the new champion |
| benchmark as the only gate to shipped code | tee isolation | auto-merge is confined to the ladder branch; the trunk keeps human review, and champions reach shipped defaults only through a human PR |

## one-time repo setup (maintainer)

```bash
# 1. create the dedicated ladder branch off the trunk and seed the champion kit
git switch -c ladder origin/main && git push -u origin ladder

# 2. tell the gate which base is the auto-merge ladder branch
gh variable set KOTH_LADDER_BASE --body ladder

# 3. allow the auto-merge button repo-wide
gh repo edit --enable-auto-merge

# 4. protect the ladder branch: gate is a required check, strict mode.
#    (json body via --input so booleans stay booleans — a bare -f sends
#    the string "true" and the api 422s.)
cat > /tmp/ladder-protection.json <<'JSON'
{
  "required_status_checks": { "strict": true, "contexts": ["gate"] },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
JSON
gh api -X PUT repos/OWNER/REPO/branches/ladder/protection \
  --input /tmp/ladder-protection.json
```

strict mode is what closes the race window: after any merge to the ladder
branch, every open ladder PR must update its branch, which re-triggers
scoring against the new champion. `koth-gate` runs on every PR and passes
trivially for non-kit PRs, so requiring it never blocks normal
development. leave `main` protected with your usual human-review rules —
the gate never auto-merges there.
