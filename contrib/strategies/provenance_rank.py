"""Provenance-aware ranking: first-hand facts over hearsay and instructions.

Three general principles, none keyed to any benchmark artifact:

1. **Hearsay demotion.** A memory that *attributes* a fact to a named third
   party via reported speech ("X mentioned her ... is", "X said his ...")
   is weaker evidence about the speaker's own facts than a first-hand
   statement — especially when the query is first-person ("my ...") or
   team-scoped ("our ...", "we ..."). Demote it below first-hand memories.

2. **Instruction demotion.** A memory that tries to *instruct the reader*
   ("always answer", "no matter what", "if anyone asks") is a stored
   prompt-injection, not a fact. It should rank behind every ordinary
   memory that matches the query.

3. **Update boost.** A memory phrased as a change of state ("changed to",
   "moved ... to", "is now") supersedes a plain assertion of the same
   attribute; surface it first so the reader sees the newest value inside
   a tight budget.

Ties and everything else defer to the backend's fused score, blended with
plain lexical overlap so an obviously-relevant hit the fusion under-ranked
still gets rescued.
"""

import re

from vouch.strategy import Candidate

_WORD = re.compile(r"[a-z0-9]+")

# reported speech about a named third party: "Foo mentioned her X is ...",
# "foo-bar said his X is ...". requires BOTH a leading name-like token and
# a speech verb with a third-person possessive, so a first-hand "i said i
# would ..." is untouched.
_HEARSAY = re.compile(
    r"\b[a-z][a-z0-9-]*\s+(?:mentioned|said|says|claims|claimed|told\s+\w+)\b"
    r".{0,40}\b(?:her|his|their)\b",
    re.IGNORECASE | re.DOTALL,
)

# stored instructions aimed at whoever reads the memory later.
_INSTRUCTION = re.compile(
    r"\b(?:always\s+answer|no\s+matter\s+what|if\s+anyone\s+asks|"
    r"future\s+assistant|ignore\s+(?:any|all|previous))\b",
    re.IGNORECASE,
)

# change-of-state phrasing: the newest value of an attribute.
_UPDATE = re.compile(
    r"\b(?:changed\s+to|moved\s+(?:\w+\s+){0,3}(?:over\s+)?to|is\s+now|"
    r"switched\s+to|renamed\s+to)\b",
    re.IGNORECASE,
)

_FIRST_PERSON_QUERY = re.compile(r"\b(?:my|our|we|i)\b", re.IGNORECASE)


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def rank(query: str, candidates: list[Candidate], *, limit: int) -> list[str]:
    q = _tokens(query)
    first_person = bool(_FIRST_PERSON_QUERY.search(query))

    def key(c: Candidate) -> float:
        text = c.summary
        overlap = len(q & _tokens(text)) / len(q) if q else 0.0
        score = 0.7 * c.score + 0.3 * overlap
        if _INSTRUCTION.search(text):
            score -= 10.0
        if _HEARSAY.search(text) and first_person:
            score -= 5.0
        elif _HEARSAY.search(text):
            score -= 2.0
        if _UPDATE.search(text):
            score += 1.0
        return score

    return [c.id for c in sorted(candidates, key=key, reverse=True)]
