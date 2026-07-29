"""The champion strategy family as bounded, reviewable data.

The engine lane ships ranking *code* through human review; this module is
what lets the ladder keep improving without that human in the day-to-day
loop. Every decision point of the reigning champion family (relevance-guard
lineage) is exposed as a bounded parameter, and a kit — pure data, scored
and auto-merged by the kit gate — can tune any of them via
``retrieval.strategy_params``.

The trust argument, spelled out because it is the whole point: a score can
auto-merge an artifact only when the score plus the artifact's structural
bounds cover everything the artifact can do. Code never clears that bar —
unexercised branches can do anything. A ``StrategyParams`` mapping does:
the interpreter below is reviewed once, ``extra="forbid"`` plus field
bounds close the space, and the worst possible submission is a badly-tuned
ranking that the next dethrone corrects. New *capabilities* (a new signal,
a new suspect class) still arrive as code through the engine lane; once
merged, their parameter space belongs to the data lane forever.

Defaults reproduce the promoted champion's constants exactly, so
``strategy_params: {}`` scores identically to the shipped default and a
kit diff reads as "what changed vs the champion".
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

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

_STOP = frozenset([
    "the", "a", "an", "is", "are", "was", "were", "my", "our", "we", "i",
    "to", "of", "for", "and", "or", "in", "on", "at", "it", "this", "that",
    "with", "about", "over", "after", "right", "now", "week", "yesterday",
    "record",
])


class StrategyParams(BaseModel):
    """Bounded knobs of the champion ranking family.

    ``extra="forbid"`` is load-bearing: an unknown key is a validation
    error, not a silent no-op, so the kit gate's closed-world rule holds
    through this subtree too. Bounds are wide enough to explore and tight
    enough that no value can invert the interpreter into something the
    reviewed code does not do.
    """

    model_config = ConfigDict(extra="forbid")

    score_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    overlap_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    # penalty = class_penalty * (1 + danger_scale * overlap): suspects fall
    # out of a tight pool in damage order, not by class weight alone.
    danger_scale: float = Field(default=4.0, ge=0.0, le=20.0)
    instruction_penalty: float = Field(default=10.0, ge=0.0, le=50.0)
    suspect_penalty: float = Field(default=6.0, ge=0.0, le=50.0)
    update_boost_topical: float = Field(default=1.0, ge=0.0, le=10.0)
    update_boost_offtopic: float = Field(default=0.1, ge=0.0, le=10.0)
    collapse_min_shared: int = Field(default=2, ge=1, le=10)
    hearsay_suspect: bool = True
    possessive_suspect: bool = True
    conflict_collapse: bool = True
    past_intent_suspends: bool = True
    strip_highlights: bool = True

    @field_validator(
        "score_weight", "overlap_weight", "danger_scale",
        "instruction_penalty", "suspect_penalty", "update_boost_topical",
        "update_boost_offtopic", "collapse_min_shared", mode="before",
    )
    @classmethod
    def _bool_is_not_a_number(cls, value: Any) -> Any:
        # yaml true is an int subclass in python and pydantic would coerce
        # it; a numeric knob must refuse it, same rule as the kit validator
        if isinstance(value, bool):
            raise ValueError("boolean is not a number")
        return value


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _content(text: str) -> set[str]:
    return _tokens(text) - _STOP


class ConfiguredStrategy:
    """The champion family interpreter: rank() driven by StrategyParams."""

    def __init__(self, params: StrategyParams | None = None) -> None:
        self.params = params or StrategyParams()

    def rank(
        self, query: str, candidates: list[Candidate], *, limit: int
    ) -> list[str]:
        p = self.params
        q = _tokens(query)
        first_person = bool(_FIRST_PERSON_QUERY.search(query))
        past_intent = p.past_intent_suspends and bool(_PAST_QUERY.search(query))

        def _clean(s: str) -> str:
            if not p.strip_highlights:
                return s
            # retrieval highlights query-matched terms with guillemets;
            # match the text, not the markup
            return s.replace(chr(171), chr(32)).replace(chr(187), chr(32))

        update_contents = [
            _content(_clean(c.summary)) for c in candidates
            if _UPDATE.search(_clean(c.summary))
        ]

        def key(c: Candidate) -> float:
            text = _clean(c.summary)
            overlap = len(q & _tokens(text)) / len(q) if q else 0.0
            score = p.score_weight * c.score + p.overlap_weight * overlap
            is_update = bool(_UPDATE.search(text))
            danger = 1.0 + p.danger_scale * overlap
            suspect = False
            if (p.hearsay_suspect and _HEARSAY.search(text)) or (
                p.possessive_suspect
                and first_person
                and _THIRD_POSSESSIVE.search(text)
            ):
                suspect = True
            if past_intent:
                pass  # history wanted: no update boost, no collapse
            elif is_update:
                topical = len(_content(text) & q) > 0
                score += (
                    p.update_boost_topical if topical else p.update_boost_offtopic
                )
            elif p.conflict_collapse and update_contents:
                mine = _content(text)
                if any(
                    len(mine & upd) >= p.collapse_min_shared
                    for upd in update_contents
                ):
                    suspect = True
            if _INSTRUCTION.search(text):
                score -= p.instruction_penalty * danger
            elif suspect:
                score -= p.suspect_penalty * danger
            return score

        return [c.id for c in sorted(candidates, key=key, reverse=True)]


def build(data: dict[str, Any]) -> ConfiguredStrategy:
    """Validate a raw ``retrieval.strategy_params`` mapping and build.

    Raises pydantic.ValidationError on any unknown key or out-of-bounds
    value — callers on the retrieval path treat that as "no strategy",
    callers on the gate path treat it as a rejected kit.
    """
    return ConfiguredStrategy(StrategyParams.model_validate(data))


def validate_params(data: Any) -> list[str]:
    """Return human-readable errors for a raw params mapping ([] = valid).

    The kit validator delegates the ``retrieval.strategy_params`` subtree
    here so the gate and the runtime can never disagree about what a legal
    kit is: one schema, two callers.
    """
    if not isinstance(data, dict):
        return ["expected a mapping"]
    try:
        StrategyParams.model_validate(data)
    except ValidationError as exc:
        return [
            f"{'.'.join(str(loc) for loc in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors()
        ]
    return []


# the dotted-path hook (`retrieval.strategy: vouch.strategies.configured`)
# resolves to the family at champion defaults.
STRATEGY = ConfiguredStrategy()
