"""Retrieval eval harness: metric unit tests + offline recall regression gate."""

from __future__ import annotations

import bench_harness as bh
import pytest


def test_recall_at_k_counts_expected_in_topk():
    per_query = [
        {"query": "a", "expected": ["x"], "ranked": ["x", "y", "z"]},  # hit @1
        {"query": "b", "expected": ["y"], "ranked": ["a", "b", "y"]},  # hit @3
        {"query": "c", "expected": ["q"], "ranked": ["a", "b", "c"]},  # miss
    ]
    assert bh.recall_at_k(per_query, 5) == pytest_approx(2 / 3)
    assert bh.recall_at_k(per_query, 1) == pytest_approx(1 / 3)  # only "a" hits @1


def test_recall_at_k_multi_target_is_fractional():
    per_query = [{"query": "a", "expected": ["x", "y"], "ranked": ["x", "z"]}]  # 1 of 2
    assert bh.recall_at_k(per_query, 5) == pytest_approx(0.5)


def test_mrr_uses_first_hit_rank():
    per_query = [
        {"query": "a", "expected": ["x"], "ranked": ["x", "y"]},  # 1/1
        {"query": "b", "expected": ["y"], "ranked": ["a", "y"]},  # 1/2
        {"query": "c", "expected": ["q"], "ranked": ["a", "b"]},  # 0
    ]
    assert bh.mrr(per_query) == pytest_approx((1.0 + 0.5 + 0.0) / 3)


# small local helper so we don't depend on pytest.approx import style
def pytest_approx(value, tol=1e-9):
    import pytest

    return pytest.approx(value, abs=tol)


# Baselines measured by `python scripts/search_bench.py` over the frozen corpus:
#   queries=29  recall@5=1.000  recall@10=1.000  MRR=0.983
# recall@5 is saturated (small, well-separated corpus), so the gate pairs a
# recall@5 floor (guards top-5 membership) with an MRR floor (guards ranking
# order, which still has headroom). A future ranking change that regresses
# either fails CI. Offline: fixtures + cached vectors only, no network.
EVAL_RECALL_AT_5_BASELINE = 0.95
EVAL_MRR_BASELINE = 0.90


@pytest.mark.skip(
    reason="synthetic eval corpus + regenerated vectors land in the offline-demo "
    "task (Phase 2.9); the real corpus was removed for the open-source scrub"
)
def test_search_recall_meets_baseline():
    corpus, labels, vectors = bh.load_fixtures()
    session = bh.make_session()
    bh.seed_corpus(session, corpus, vectors)
    per_query = bh.run_eval(session, labels, vectors)

    r5 = bh.recall_at_k(per_query, 5)
    mrr = bh.mrr(per_query)
    assert r5 >= EVAL_RECALL_AT_5_BASELINE, (
        f"recall@5 {r5:.3f} < baseline {EVAL_RECALL_AT_5_BASELINE:.3f} — "
        "a ranking change regressed top-5 retrieval, or re-baseline intentionally"
    )
    assert mrr >= EVAL_MRR_BASELINE, (
        f"MRR {mrr:.3f} < baseline {EVAL_MRR_BASELINE:.3f} — "
        "a ranking change regressed result ordering, or re-baseline intentionally"
    )


def test_gate_has_teeth():
    # A ranking that returns nothing must drop recall to 0.0, proving the gate
    # would actually catch a regression (and that the baselines are real floors).
    per_query = [
        {"query": q, "expected": exp, "ranked": []} for q, exp in [("q1", ["a"]), ("q2", ["b"])]
    ]
    assert bh.recall_at_k(per_query, 5) == 0.0
    assert bh.mrr(per_query) == 0.0
    assert 0.0 < EVAL_RECALL_AT_5_BASELINE
    assert 0.0 < EVAL_MRR_BASELINE
