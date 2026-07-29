"""The koth kit validator — the closed-world allowlist that lets a kit-only
PR auto-merge without a human. Every test here guards a way an untrusted kit
could smuggle something past the gate."""

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "validate_kit",
    Path(__file__).resolve().parents[1] / ".github" / "scripts" / "validate_kit.py",
)
assert _SPEC and _SPEC.loader
validate_kit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(validate_kit)
validate = validate_kit.validate

CHAMPION = (
    Path(__file__).resolve().parents[1]
    / "competition"
    / "kits"
    / "current"
    / "kit.yaml"
).read_text(encoding="utf-8")


def test_champion_kit_validates() -> None:
    assert validate(CHAMPION) == []


def test_empty_kit_is_rejected() -> None:
    # the >1MB contents-api bypass: an oversized file returns empty content,
    # which must NOT validate as "champion defaults".
    assert validate("") != []
    assert validate("   \n  \n") != []


def test_kit_without_retrieval_section_is_rejected() -> None:
    assert validate("review:\n  auto_approve_on_receipt: true\n") != []


def test_command_key_is_rejected() -> None:
    # config can name executables (compile.llm_cmd); a kit must never reach one.
    errors = validate("retrieval:\n  backend: auto\ncompile:\n  llm_cmd: 'sh -c evil'\n")
    assert any("not in allowlist" in e for e in errors)


def test_unknown_retrieval_key_is_rejected() -> None:
    errors = validate("retrieval:\n  backend: auto\n  secret_knob: 1\n")
    assert any("not in allowlist" in e for e in errors)


def test_out_of_bounds_values_are_rejected() -> None:
    assert validate("retrieval:\n  backend: nonsense\n") != []
    assert validate("retrieval:\n  recency:\n    half_life_days: 99999\n") != []
    assert validate("retrieval:\n  rerank:\n    top_k: 0\n") != []
    assert validate("retrieval:\n  pages_first:\n    boost: -1\n") != []


def test_bool_is_not_accepted_as_a_number() -> None:
    # yaml true is an int subclass in python; a numeric knob must refuse it.
    assert validate("retrieval:\n  recency:\n    half_life_days: true\n") != []


def test_oversized_kit_is_rejected() -> None:
    big = "retrieval:\n  backend: auto\n" + ("# pad\n" * 2000)
    assert any("larger than" in e for e in validate(big))


def test_strategy_params_kit_validates() -> None:
    # the data lane for ranking: champion-family knobs are legal kit surface.
    kit = (
        "retrieval:\n"
        "  backend: auto\n"
        "  strategy_params:\n"
        "    suspect_penalty: 3.5\n"
        "    danger_scale: 6.0\n"
        "    conflict_collapse: false\n"
    )
    assert validate(kit) == []


def test_strategy_params_out_of_bounds_is_rejected() -> None:
    errors = validate(
        "retrieval:\n  strategy_params:\n    score_weight: 1.5\n"
    )
    assert any("strategy_params.score_weight" in e for e in errors)


def test_strategy_params_unknown_knob_is_rejected() -> None:
    # extra=forbid in the schema keeps the closed world closed through
    # the delegated subtree.
    errors = validate(
        "retrieval:\n  strategy_params:\n    eval_hook: 'evil'\n"
    )
    assert errors != []


def test_strategy_params_bool_is_not_a_number() -> None:
    errors = validate(
        "retrieval:\n  strategy_params:\n    danger_scale: true\n"
    )
    assert errors != []


def test_strategy_params_must_be_a_mapping() -> None:
    errors = validate("retrieval:\n  strategy_params: [1, 2]\n")
    assert any("expected a mapping" in e for e in errors)


def test_dotted_strategy_key_is_rejected() -> None:
    # naming code to import is not data; only strategy_params is kit surface.
    errors = validate(
        "retrieval:\n  strategy: vouch.strategies.provenance\n"
    )
    assert any("not in allowlist" in e for e in errors)
