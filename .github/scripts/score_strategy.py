"""Paired champion-vs-challenger scoring for the engine (strategy) lane.

Same dethrone test as the kit lane (docs/vouchbench-seasons.md), but the arm
is a pluggable ranking strategy instead of a config fragment: each submission
is loaded as an untrusted file and run through vouch.strategy.SandboxProxy, so
the scored code executes only inside the sandbox child.

    dethroned  iff  mean(challenger - champion)  >=  max(0.007, 1.96 x SE)

Exit code 0 = dethroned, 3 = held, 1 = error. Unlike the kit lane, a winning
verdict here does NOT auto-merge: engine code ships only through human review.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

from vouch import bench
from vouch.strategy import SandboxProxy

N_SEEDS = 8
FLOOR = bench.DETHRONE_FLOOR
Z = bench.DETHRONE_Z
SESSION_GAP_SECONDS = 2.0


def day_seeds(base_sha: str, date: str, n: int = N_SEEDS) -> list[int]:
    seeds = []
    for i in range(n):
        digest = hashlib.sha256(f"{base_sha}:{date}:{i}".encode()).hexdigest()
        seeds.append(int(digest[:12], 16))
    return seeds


def score(path: str, seeds: list[int]) -> list[float]:
    proxy = SandboxProxy(path)
    return [
        bench.run(s, strategy=proxy, session_gap_seconds=SESSION_GAP_SECONDS)[
            "composite"
        ]
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

    champion_scores = score(args.champion, seeds)
    challenger_scores = score(args.challenger, seeds)
    verdict = bench.paired_verdict(
        champion_scores, challenger_scores, floor=FLOOR, z=Z,
    )

    report = {
        "date": date,
        "base_sha": args.base_sha,
        "seeds": seeds,
        "lane": "engine",
        **verdict,
    }
    text = json.dumps(report, indent=1)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0 if report["dethroned"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
