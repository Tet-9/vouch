"""Paired champion-vs-challenger scoring for the koth ladder.

Runs vouchbench twice per seed — once with the reigning kit, once with the
challenger kit — over seeds derived from the base sha and the utc date, and
applies the dethrone test from docs/vouchbench-seasons.md:

    dethroned  iff  mean(challenger - champion)  >=  max(0.007, 1.96 x SE)

where SE is the standard error of the per-seed paired differences (common
random numbers: both arms see identical generated sessions per seed, so the
difference cancels seed-to-seed variance).

Seeds are deterministic for a given (base sha, utc day): anyone can recompute
the day's seeds and reproduce the run locally. Same-day overfitting to known
seeds is bounded by the margin band and settled monthly by the season's
commit-reveal scored run, which uses seeds that do not exist until the
cutoff.

Usage:
    python koth_score.py --champion kit.yaml --challenger kit-pr.yaml \
        --base-sha <sha> [--date YYYY-MM-DD] [--out report.json]

Exit code 0 = dethroned (challenger wins), 3 = held (champion stands),
1 = error. The distinct win/hold codes let the workflow branch without
parsing the report.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

from vouch import bench

# 12 paired seeds, not 4: the band is built from the standard error of the
# paired differences, and n=4 makes that SE noisy and its normal-z reading
# optimistic. z=1.96 is the two-sided 95% normal quantile; with a small n
# the paired diffs are not perfectly normal, so the floor below still does
# the real gatekeeping when the SE collapses on a deterministic overfit.
N_SEEDS = 12
FLOOR = bench.DETHRONE_FLOOR
Z = bench.DETHRONE_Z
# bench sleeps this long between session ingests to spread created_at
# timestamps; keep it small — it is wall-clock, not simulated time. the
# 3600s that lived here briefly would have out-slept the CI job timeout
# many times over.
SESSION_GAP_SECONDS = 2.0


def day_seeds(base_sha: str, date: str, n: int = N_SEEDS) -> list[int]:
    """Derive the day's seed list from the champion sha and the utc date."""
    seeds = []
    for i in range(n):
        digest = hashlib.sha256(f"{base_sha}:{date}:{i}".encode()).hexdigest()
        seeds.append(int(digest[:12], 16))
    return seeds


def score(kit_text: str, seeds: list[int]) -> list[float]:
    extra = kit_text if kit_text.strip() else None
    return [
        bench.run(
            s, extra_config=extra, session_gap_seconds=SESSION_GAP_SECONDS
        )["composite"]
        for s in seeds
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--champion", required=True)
    parser.add_argument("--challenger", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--date", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    date = args.date or dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    seeds = day_seeds(args.base_sha, date)

    champion_text = Path(args.champion).read_text(encoding="utf-8")
    challenger_text = Path(args.challenger).read_text(encoding="utf-8")

    champion_scores = score(champion_text, seeds)
    challenger_scores = score(challenger_text, seeds)
    verdict = bench.paired_verdict(
        champion_scores, challenger_scores, floor=FLOOR, z=Z,
    )

    report = {
        "date": date,
        "base_sha": args.base_sha,
        "seeds": seeds,
        "lane": "kit",
        **verdict,
    }
    text = json.dumps(report, indent=1)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0 if report["dethroned"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
