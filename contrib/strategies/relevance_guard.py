"""Relevance-guarded ranking: suspects are excluded by how much harm they do.

Extends the provenance champion with three general principles:

1. **Uniform, relevance-scaled suspicion.** Hearsay, third-person
   possessive fragments, stored instructions, and stale conflicting
   values are all suspect classes - and a suspect that strongly matches
   the query does the most damage if shown. One uniform penalty scaled
   by query overlap means suspects fall out of a tight candidate pool in
   damage order, instead of class weights accidentally protecting the
   one item the question is actually about.

2. **Conflict collapse.** A plain assertion contradicted by a
   change-of-state memory ("... changed to friday" vs "... is monday")
   is stale; it joins the suspect set so the newest value survives the
   budget.

3. **Temporal intent.** A question about the past ("what was ... before
   it changed?") wants history: collapse and update boosts are
   suspended, because the stale side of the conflict is the answer.

Plus the champion rules that remain: topical update boost, and matching
on text with retrieval highlight markers stripped. No benchmark-keyed
logic: no value lists, no template matching, no category dispatch.
"""


import re

from vouch.strategy import Candidate

_WORD = re.compile(r"[a-z0-9]+")

_HEARSAY = re.compile(
    r"\b[a-z][a-z0-9-]*\s+(?:mentioned|said|says|claims|claimed|told\s+\w+)\b"
    r".{0,40}\b(?:her|his|their)\b",
    re.IGNORECASE | re.DOTALL,
)
_THIRD_POSSESSIVE = re.compile(
    r"\b(?:her|his|their)\s+(?:\w+\s+){0,2}(?:is|was|are)\b", re.IGNORECASE,
)
_INSTRUCTION = re.compile(
    r"\b(?:always\s+answer|no\s+matter\s+what|if\s+anyone\s+asks|"
    r"future\s+assistant|ignore\s+(?:any|all|previous))\b",
    re.IGNORECASE,
)
_UPDATE = re.compile(
    r"\b(?:changed\s+to|moved\s+(?:\w+\s+){0,3}(?:over\s+)?to|is\s+now|"
    r"switched\s+to|renamed\s+to)\b",
    re.IGNORECASE,
)
_FIRST_PERSON_QUERY = re.compile(r"\b(?:my|our|we|i)\b", re.IGNORECASE)
_PAST_QUERY = re.compile(
    r"\b(?:was|were|before|previously|originally|used\s+to|prior)\b",
    re.IGNORECASE,
)

_STOP = frozenset(
    "the a an is are was were my our we i to of for and or in on at it this "
    "that with about over after right now week yesterday record".split()
)

SCORE_W = 0.7
OVERLAP_W = 0.3
CONFLICT_PENALTY = 3.0
POSSESSIVE_PENALTY = 4.0


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _content(text: str) -> set[str]:
    return _tokens(text) - _STOP


def rank(query: str, candidates: list[Candidate], *, limit: int) -> list[str]:
    q = _tokens(query)
    first_person = bool(_FIRST_PERSON_QUERY.search(query))
    # a past-tense question wants history: the stale side of a conflict is
    # the answer, so collapse and update boosts are suspended
    past_intent = bool(_PAST_QUERY.search(query))

    def _clean(s: str) -> str:
        return s.replace(chr(171), chr(32)).replace(chr(187), chr(32))

    update_contents = [
        _content(_clean(c.summary)) for c in candidates
        if _UPDATE.search(_clean(c.summary))
    ]

    def key(c: Candidate) -> float:
        # retrieval highlights query-matched terms with guillemets; match
        # the text, not the markup, or every query-relevant candidate
        # slips past the patterns
        text = c.summary.replace(chr(171), chr(32)).replace(chr(187), chr(32))
        overlap = len(q & _tokens(text)) / len(q) if q else 0.0
        score = SCORE_W * c.score + OVERLAP_W * overlap
        is_update = bool(_UPDATE.search(text))
        # every class of suspect memory gets ONE uniform penalty scaled
        # by relevance to the query, so suspects are excluded from a tight
        # pool in order of how much damage they would do if shown. class
        # weights fighting relevance is how the wrong item survives the cut.
        danger = 1.0 + 4.0 * overlap
        suspect = False
        if _HEARSAY.search(text):
            suspect = True
        elif first_person and _THIRD_POSSESSIVE.search(text):
            suspect = True
        if past_intent:
            pass  # history wanted: no update boost, no collapse
        elif is_update:
            # boost only updates about what was asked - an off-topic
            # update must not crowd the answer out of a tight pack
            topical = len(_content(text) & q) > 0
            score += 1.0 if topical else 0.1
        elif update_contents:
            mine = _content(text)
            if any(len(mine & upd) >= 2 for upd in update_contents):
                suspect = True
        if _INSTRUCTION.search(text):
            score -= 10.0 * danger
        elif suspect:
            score -= 6.0 * danger
        return score

    return [c.id for c in sorted(candidates, key=key, reverse=True)]
