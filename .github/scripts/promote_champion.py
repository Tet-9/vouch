"""Promote a merged engine-lane winner to reigning champion.

The dethrone band vs the current champion IS the merge threshold; this
script is the ratchet that raises it. After a human merges a winning
strategy PR, the ledger sweep calls this to copy the winner over
``contrib/strategies/baseline.py`` (the file both gates score challengers
against), so the next challenger must beat the new champion — the
threshold updates itself on every merge.

The copy carries a provenance header naming the source file, the PR, and
the scored mean at promotion time. Idempotent: promoting the same file
twice leaves the champion byte-identical.

Usage:
    python promote_champion.py --strategy contrib/strategies/<name>.py \
        --pr 123 --mean 0.6250 [--champion contrib/strategies/baseline.py]

Exit 0 = promoted (or already champion), 1 = error.
"""

from __future__ import annotations

import argparse
from pathlib import Path

HEADER = '''"""The reigning engine-lane champion (auto-promoted, do not edit).

Promoted from ``{source}`` (PR #{pr}, scored mean {mean} at promotion).
Both gates score challengers against this file; dethrone it by opening a
PR that adds one new file under ``contrib/strategies/`` and clears
max(0.007, 1.96 x paired SE) over the day's seeds. On merge, the ledger
sweep promotes the winner here automatically - the threshold ratchets.
"""

'''


def promote(strategy: Path, champion: Path, pr: int, mean: float) -> bool:
    """Copy winner over champion with a provenance header. True = changed."""
    body = strategy.read_text(encoding="utf-8")
    # drop the submission's own module docstring so the champion header is
    # the single source of provenance
    stripped = body
    if stripped.startswith('"""'):
        end = stripped.find('"""', 3)
        if end != -1:
            stripped = stripped[end + 3 :].lstrip("\n")
    new = HEADER.format(source=strategy.as_posix(), pr=pr, mean=f"{mean:.4f}")
    new += stripped
    if champion.exists() and champion.read_text(encoding="utf-8") == new:
        return False
    champion.write_text(new, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--mean", required=True, type=float)
    parser.add_argument(
        "--champion", default="contrib/strategies/baseline.py",
    )
    args = parser.parse_args()

    strategy = Path(args.strategy)
    if not strategy.is_file():
        print(f"strategy file not found: {strategy}")
        return 1
    changed = promote(strategy, Path(args.champion), args.pr, args.mean)
    print("champion promoted" if changed else "already the champion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
