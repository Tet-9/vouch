"""Validate a ladder kit file against the strict allowlist.

The kit is the one file an untrusted PR may change, and it is applied as
extra_config inside a write-token CI context — so the surface must be data
only. In particular, config keys that name executables (compile.llm_cmd,
enrich.llm_cmd) must never be reachable from a kit: a kit that could set a
command string would execute it on the runner. The allowlist below is
therefore closed-world: unknown keys are an error, not a warning.

Usage: python validate_kit.py <kit.yaml>
Exits 0 and prints the canonical yaml on success; exits 1 with a reason
on any violation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

MAX_KIT_BYTES = 4096

BACKENDS = {"auto", "fts5", "embedding", "hybrid", "substring"}

# key path -> (type, validator)
BOUNDS: dict[tuple[str, ...], Any] = {
    ("retrieval", "backend"): lambda v: isinstance(v, str) and v in BACKENDS,
    ("retrieval", "default_limit"): lambda v: (
        isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 100
    ),
    ("retrieval", "prompt_gate", "enabled"): lambda v: isinstance(v, bool),
    ("retrieval", "recency", "enabled"): lambda v: isinstance(v, bool),
    ("retrieval", "recency", "half_life_days"): lambda v: (
        isinstance(v, (int, float))
        and not isinstance(v, bool)
        and 0.01 <= float(v) <= 3650.0
    ),
    ("retrieval", "rerank", "enabled"): lambda v: isinstance(v, bool),
    ("retrieval", "rerank", "top_k"): lambda v: (
        isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 500
    ),
    ("retrieval", "pages_first", "enabled"): lambda v: isinstance(v, bool),
    ("retrieval", "pages_first", "boost"): lambda v: (
        isinstance(v, (int, float))
        and not isinstance(v, bool)
        and 0.1 <= float(v) <= 10.0
    ),
}

ALLOWED_BRANCHES = {path[:i] for path in BOUNDS for i in range(1, len(path))}

# The champion-family knobs (retrieval.strategy_params) are validated by the
# same pydantic schema the runtime builds the strategy from — one schema, two
# callers, so the gate and the engine can never disagree about a legal kit.
# The subtree stays data-only: the schema forbids unknown keys and bounds
# every value, and the dotted code hook (retrieval.strategy) is deliberately
# NOT in the allowlist — naming code to import is not data.
STRATEGY_PARAMS = ("retrieval", "strategy_params")


def _validate_strategy_params(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["retrieval.strategy_params: expected a mapping"]
    try:
        from vouch.strategies.configured import validate_params
    except ImportError:
        # fail closed: a kit touching strategy_params cannot be judged
        # without the schema, and "cannot judge" must never mean "pass".
        return [
            "retrieval.strategy_params: the vouch package is required to "
            "validate this section (pip install -e .)"
        ]
    return [f"retrieval.strategy_params.{err}" for err in validate_params(value)]


def _walk(node: Any, path: tuple[str, ...], errors: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if not isinstance(key, str):
                errors.append(f"non-string key at {'.'.join(path) or '<root>'}")
                continue
            child = (*path, key)
            if child == STRATEGY_PARAMS:
                errors.extend(_validate_strategy_params(value))
            elif child in BOUNDS:
                if not BOUNDS[child](value):
                    errors.append(f"{'.'.join(child)}: value {value!r} out of bounds")
            elif child in ALLOWED_BRANCHES:
                _walk(value, child, errors)
            else:
                errors.append(f"{'.'.join(child)}: key not in allowlist")
    else:
        errors.append(f"{'.'.join(path) or '<root>'}: expected a mapping")


def validate(text: str) -> list[str]:
    # an empty kit must NOT validate: over the contents-api, a file larger
    # than the api's inline limit comes back with empty content, which would
    # otherwise decode to "" and pass vacuously — the PR would then be scored
    # as engine defaults rather than its real, oversized contents. require a
    # real retrieval mapping so "empty" can never mean "champion defaults".
    encoded = text.encode("utf-8")
    if not encoded.strip():
        return ["empty kit (nothing to score — did the fetch truncate?)"]
    if len(encoded) > MAX_KIT_BYTES:
        return [f"kit larger than {MAX_KIT_BYTES} bytes"]
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [f"not valid yaml: {exc}"]
    if not isinstance(data, dict) or "retrieval" not in data:
        return ["kit must be a mapping with a top-level 'retrieval' section"]
    errors: list[str] = []
    _walk(data, (), errors)
    return errors


def main() -> int:
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    errors = validate(text)
    if errors:
        for err in errors:
            print(f"kit rejected: {err}", file=sys.stderr)
        return 1
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
