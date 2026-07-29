"""Append a dethrone row to competition/LEADERBOARD.md from a scorecard.

The ledger row was appended by hand at season close; every dethrone that
lands on the ladder branch now writes its own row. Input is the report
json both scorers emit (koth_score.py for kits, score_strategy.py for
strategies — same shape, ``lane`` distinguishes them).

Idempotent on the PR number: if the ledger already cites the PR, the
script exits 0 without writing, so the ledger workflow re-running on its
own push converges instead of looping.

Usage:
    python update_leaderboard.py --report report.json --pr 123 \
        --author somebody [--ledger competition/LEADERBOARD.md]

Exit code 0 = row appended or already present, 1 = error.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def next_row_number(ledger_text: str) -> int:
    rows = re.findall(r"^\| (\d+) \|", ledger_text, flags=re.M)
    return max((int(r) for r in rows), default=-1) + 1


def format_row(
    number: int, report: dict, pr: int, author: str
) -> str:
    lane = report.get("lane", "kit")
    date = report.get("date", "")
    mean = report["challenger"]["mean"]
    margin = report["mean_diff"]
    return (
        f"| {number} | {author} ({lane}) | #{pr} | {date} "
        f"| {mean:.4f} | +{margin:.4f} |"
    )


def append_row(ledger: Path, report: dict, pr: int, author: str) -> bool:
    """Add the row unless the PR is already cited. True = file changed."""
    text = ledger.read_text(encoding="utf-8")
    if re.search(rf"\| #{pr} \|", text):
        return False
    row = format_row(next_row_number(text), report, pr, author)
    if not text.endswith("\n"):
        text += "\n"
    # the table is the last block before the payout footer; append right
    # after the final table row so the footer prose stays at the bottom
    lines = text.splitlines(keepends=True)
    last_row = max(
        i for i, line in enumerate(lines) if line.startswith("| ")
    )
    lines.insert(last_row + 1, row + "\n")
    ledger.write_text("".join(lines), encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--author", required=True)
    parser.add_argument(
        "--ledger", default="competition/LEADERBOARD.md",
    )
    args = parser.parse_args()

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    if not report.get("dethroned"):
        print("report is not a dethrone; nothing to append")
        return 0
    changed = append_row(Path(args.ledger), report, args.pr, args.author)
    print("row appended" if changed else f"pr #{args.pr} already in ledger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
