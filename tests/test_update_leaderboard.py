"""The ledger appender — every dethrone that lands on the ladder branch
writes its own LEADERBOARD.md row. These tests guard the row math and the
idempotency that lets the ledger workflow re-trigger on its own push."""

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "update_leaderboard",
    Path(__file__).resolve().parents[1]
    / ".github" / "scripts" / "update_leaderboard.py",
)
assert _SPEC and _SPEC.loader
update_leaderboard = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(update_leaderboard)

BASELINE_ROW = "| 0 | baseline kit (repo defaults) | - | 2026-07-28 | 0.52 | - |"

LEDGER = f"""# koth ladder — throne history

prose above the table.

| # | champion | PR | dethroned on | scored mean | margin over prior |
|---|----------|----|--------------|-------------|-------------------|
{BASELINE_ROW}

payout footer prose stays at the bottom.
"""

REPORT = {
    "date": "2026-07-29",
    "lane": "engine",
    "challenger": {"scores": [0.6, 0.62], "mean": 0.61},
    "mean_diff": 0.09,
    "dethroned": True,
}


def test_next_row_number_continues_the_table() -> None:
    assert update_leaderboard.next_row_number(LEDGER) == 1
    assert update_leaderboard.next_row_number("no table yet") == 0


def test_append_row_lands_after_last_row(tmp_path: Path) -> None:
    ledger = tmp_path / "LEADERBOARD.md"
    ledger.write_text(LEDGER, encoding="utf-8")
    changed = update_leaderboard.append_row(ledger, REPORT, 123, "alice-example")
    assert changed
    lines = ledger.read_text(encoding="utf-8").splitlines()
    row = "| 1 | alice-example (engine) | #123 | 2026-07-29 | 0.6100 | +0.0900 |"
    assert row in lines
    # the new row sits directly under the baseline row, above the footer
    assert lines.index(row) == lines.index(BASELINE_ROW) + 1


def test_append_row_is_idempotent_per_pr(tmp_path: Path) -> None:
    ledger = tmp_path / "LEADERBOARD.md"
    ledger.write_text(LEDGER, encoding="utf-8")
    assert update_leaderboard.append_row(ledger, REPORT, 123, "alice-example")
    before = ledger.read_text(encoding="utf-8")
    assert not update_leaderboard.append_row(ledger, REPORT, 123, "alice-example")
    assert ledger.read_text(encoding="utf-8") == before
