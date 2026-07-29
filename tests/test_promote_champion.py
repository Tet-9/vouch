"""The champion ratchet — a merged engine winner becomes the file both
gates score challengers against, so the merge threshold rises on its own.
These tests guard the copy mechanics and the idempotency the ledger sweep
relies on."""

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "promote_champion",
    Path(__file__).resolve().parents[1]
    / ".github" / "scripts" / "promote_champion.py",
)
assert _SPEC and _SPEC.loader
promote_champion = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(promote_champion)

WINNER = '''"""My clever submission docstring."""

def rank(query, candidates, *, limit):
    return [c.id for c in candidates]
'''


def test_promote_copies_with_provenance_header(tmp_path: Path) -> None:
    winner = tmp_path / "clever.py"
    winner.write_text(WINNER, encoding="utf-8")
    champion = tmp_path / "baseline.py"
    changed = promote_champion.promote(winner, champion, 42, 0.625)
    assert changed
    text = champion.read_text(encoding="utf-8")
    assert "PR #42" in text and "0.6250" in text
    assert "def rank(" in text
    # the submission's own docstring is dropped; the header is the single
    # source of provenance
    assert "clever submission docstring" not in text
    compile(text, "champion", "exec")


def test_promote_is_idempotent(tmp_path: Path) -> None:
    winner = tmp_path / "clever.py"
    winner.write_text(WINNER, encoding="utf-8")
    champion = tmp_path / "baseline.py"
    assert promote_champion.promote(winner, champion, 42, 0.625)
    assert not promote_champion.promote(winner, champion, 42, 0.625)
