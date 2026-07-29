"""A worked example: re-rank by lexical overlap with the query.

Not necessarily a winner - it exists to show the shape of a real submission.
It boosts candidates whose summary shares more words with the query, blended
with the backend's own score so a strong retrieval signal is not thrown away.

Copy this file, change the scoring, and open a PR that touches only your new
file under contrib/strategies/. The engine gate scores it in a sandbox against
the reigning champion; you never edit the engine itself.
"""

import re

from vouch.strategy import Candidate

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def rank(query: str, candidates: list[Candidate], *, limit: int) -> list[str]:
    q = _tokens(query)
    if not q:
        return [c.id for c in candidates]

    def blended(c: Candidate) -> float:
        overlap = len(q & _tokens(c.summary)) / len(q)
        # keep the backend score in the mix; overlap only tips ties and
        # rescues a lexically-obvious hit the fusion under-ranked.
        return 0.7 * c.score + 0.3 * overlap

    return [c.id for c in sorted(candidates, key=blended, reverse=True)]
