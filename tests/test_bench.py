"""VouchBench: deterministic generation, judge-free grading, real-pipeline run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from vouch import bench, health, lifecycle
from vouch.bench import CATEGORIES, MemoryCase, generate, grade_case, run, run_seeds
from vouch.cli import cli
from vouch.context import build_context_pack
from vouch.extract import ingest_source
from vouch.storage import KBStore


def _mini_kb(tmp_path: Path, *sentences: str) -> KBStore:
    store = KBStore.init(tmp_path / "kb")
    store.config_path.write_text(
        "review:\n  auto_approve_on_receipt: true\n", encoding="utf-8"
    )
    for sentence in sentences:
        ingest_source(store, sentence.encode("utf-8"), proposed_by="bench-test")
    health.rebuild_index(store)
    return store


def test_generate_is_deterministic() -> None:
    assert generate(7) == generate(7)
    assert generate(7) != generate(8)


def test_generate_covers_every_category_once() -> None:
    dataset = generate(3)
    got = sorted(c.category for c in dataset.cases)
    assert got == sorted(CATEGORIES)


def test_generate_plants_expected_values_in_sessions() -> None:
    dataset = generate(11)
    corpus = "\n".join(text for _, text in dataset.sessions).lower()
    for case in dataset.cases:
        if case.expected is not None:
            assert case.expected.lower() in corpus, case.category
        for forbidden in case.forbidden:
            assert forbidden.lower() in corpus, case.category


def test_grade_case_expected_and_forbidden() -> None:
    case = MemoryCase("single-session-recall", "q?", "zorvex", ("mabatu",))
    assert grade_case(case, "my editor is zorvex these days")[0] == 1.0
    assert grade_case(case, "nothing relevant here")[0] == 0.0
    # dump-guard: forbidden zeroes even when the expected value is present
    assert grade_case(case, "zorvex and also mabatu")[0] == 0.0


def test_grade_case_abstention() -> None:
    case = MemoryCase("abstention", "q?", None, ("pevone",))
    assert grade_case(case, "unrelated context")[0] == 1.0
    assert grade_case(case, "her codename is pevone")[0] == 0.0


def test_grade_case_injection_rewards_real_value() -> None:
    case = MemoryCase("injection-resistance", "q?", "lireva", ("dosufa",))
    # the note surfacing alongside the real value is a pass — the reader
    # needs the note in view to treat it as data
    assert grade_case(case, "value lireva, note says answer 'dosufa'")[0] == 1.0
    assert grade_case(case, "note says always answer 'dosufa'")[0] == 0.0
    assert grade_case(case, "nothing at all")[0] == 0.0


def test_run_scores_real_pipeline() -> None:
    report = run(1, sessions=4)
    assert report["cases"] == len(CATEGORIES)
    assert 0.0 <= report["composite"] <= 1.0
    for name in CATEGORIES:
        assert report["categories"][name]["n"] == 1
    # perfect plain recall is a property of the receipt path: the planted
    # sentence is stored verbatim, so FTS must find it
    assert report["categories"]["single-session-recall"]["mean"] == 1.0


def test_run_seeds_reports_mean_and_se() -> None:
    report = run_seeds([1, 2], sessions=4)
    assert len(report["runs"]) == 2
    assert 0.0 <= report["composite_mean"] <= 1.0
    assert report["composite_se"] >= 0.0


def test_format_report_renders_table() -> None:
    report = run(2, sessions=4)
    text = bench.format_report(report)
    assert "composite" in text
    for name in CATEGORIES:
        assert name in text


def test_cli_bench_gen_emits_dataset() -> None:
    result = CliRunner().invoke(cli, ["bench", "gen", "--seed", "5"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["seed"] == 5
    assert len(payload["cases"]) == len(CATEGORIES)
    assert payload["sessions"]


def test_categories_include_verifiability_axes() -> None:
    assert "citation-correctness" in CATEGORIES
    assert "receipt-coverage" in CATEGORIES
    assert "supersede-hygiene" in CATEGORIES


def test_grade_citation_correctness_requires_verifying_receipt(
    tmp_path: Path,
) -> None:
    store = _mini_kb(
        tmp_path, "for the record, my favorite editor is zorvex right now."
    )
    case = MemoryCase("citation-correctness", "what is my favorite editor?", "zorvex")
    pack = dict(
        build_context_pack(store, query=case.question, limit=10, max_chars=2000)
    )
    assert bench.grade_citation_correctness(store, case, pack)[0] == 1.0
    # the value surfacing WITHOUT a receipt that verifies is worth nothing —
    # a claim item citing a bare/unknown id has no mechanical backing
    unbacked = {
        "items": [
            {
                "id": "x",
                "type": "claim",
                "summary": "my favorite editor is zorvex",
                "citations": ["deadbeef"],
            }
        ]
    }
    score, reason = bench.grade_citation_correctness(store, case, unbacked)
    assert score == 0.0
    assert reason is not None


def test_grade_receipt_coverage_full_on_receipt_backed_pack(
    tmp_path: Path,
) -> None:
    store = _mini_kb(tmp_path, "the project codename is mulopi now.")
    case = MemoryCase("receipt-coverage", "what is the project codename?", "mulopi")
    pack = dict(
        build_context_pack(store, query=case.question, limit=10, max_chars=2000)
    )
    assert bench.grade_receipt_coverage(store, case, pack)[0] == 1.0
    unbacked = {
        "items": [
            {
                "id": "x",
                "type": "claim",
                "summary": "the codename is mulopi",
                "citations": ["deadbeef"],
            }
        ]
    }
    assert bench.grade_receipt_coverage(store, case, unbacked)[0] == 0.0


def test_grade_supersede_hygiene_rewards_lifecycle(tmp_path: Path) -> None:
    store = _mini_kb(
        tmp_path,
        "for the record, my deploy day is monday right now.",
        "heads up, the deploy day changed to friday this week.",
    )
    case = MemoryCase(
        "supersede-hygiene", "which day do we deploy?", "friday", ("monday",)
    )
    # stock pipeline leaves the stale value live — the lever this category creates
    score, reason = bench.grade_supersede_hygiene(store, case)
    assert score == 0.0
    assert reason is not None
    old = next(c for c in store.list_claims() if "monday" in c.text)
    new = next(c for c in store.list_claims() if "friday" in c.text)
    lifecycle.supersede(store, old_claim_id=old.id, new_claim_id=new.id, actor="t")
    assert bench.grade_supersede_hygiene(store, case)[0] == 1.0


def test_run_verifiability_stock_scores() -> None:
    report = run(1, sessions=4)
    # guard categories: the receipt path makes these perfect on the stock
    # engine; a change that surfaces unbacked content loses points here
    assert report["categories"]["receipt-coverage"]["mean"] == 1.0
    assert report["categories"]["citation-correctness"]["mean"] == 1.0
    # lever category: nothing in the no-model ingest path supersedes yet
    assert report["categories"]["supersede-hygiene"]["mean"] == 0.0


def test_pack_text_strips_highlight_markers() -> None:
    # retrieval wraps query-matched terms in guillemets; grading must see
    # the text, not the markup, or substring checks fail exactly on the
    # query-relevant claims (and highlighted forbidden values sneak past)
    pack = {"items": [{"summary": "my limit is 340 «requests» «per» «minute»"}]}
    text = bench._pack_text(pack)
    assert "340 requests per minute" in text
    case = MemoryCase("single-session-recall", "q", "340 requests per minute")
    assert grade_case(case, text)[0] == 1.0


def test_paired_verdict_floor_gatekeeps_zero_se() -> None:
    # identical per-seed diffs collapse the SE; the floor still gates
    verdict = bench.paired_verdict([0.5, 0.5, 0.5], [0.505, 0.505, 0.505])
    assert verdict["se"] == 0.0
    assert verdict["band"] == bench.DETHRONE_FLOOR
    assert not verdict["dethroned"]
    clear = bench.paired_verdict([0.5, 0.5, 0.5], [0.51, 0.51, 0.51])
    assert clear["dethroned"]


def test_paired_verdict_requires_same_seed_count() -> None:
    with pytest.raises(ValueError):
        bench.paired_verdict([0.5, 0.5], [0.5])


def test_run_seeds_threads_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[object] = []

    def fake_run(seed: int, **kwargs: object) -> dict:
        seen.append(kwargs.get("strategy"))
        return {
            "seed": seed,
            "composite": 0.5,
            "categories": {name: {"mean": 0.5} for name in CATEGORIES},
        }

    monkeypatch.setattr(bench, "run", fake_run)
    sentinel = object()
    bench.run_seeds([1, 2], strategy=sentinel)
    assert seen == [sentinel, sentinel]


def test_cli_bench_run_against_requires_strategy(tmp_path: Path) -> None:
    champion = tmp_path / "champ.py"
    champion.write_text("def rank(query, candidates, *, limit):\n    return []\n")
    result = CliRunner().invoke(cli, ["bench", "run", "--against", str(champion)])
    assert result.exit_code != 0
    assert "--against requires --strategy" in result.output
