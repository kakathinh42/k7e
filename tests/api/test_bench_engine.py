"""The bench engine seeds SQLite and drives the real HybridSearchProvider."""

from __future__ import annotations

import bench_harness as bh


def test_run_eval_ranks_target_via_vector_similarity():
    # Three single-chunk pages with orthogonal unit vectors. Query text shares
    # NO lexical tokens with the bodies, so keyword score is 0 and ONLY vector
    # similarity drives ranking (the relevance gate drops vec < 0.3).
    corpus = {
        "cats-page": {"title": "Cats", "body": "Feline companions roam quietly."},
        "dogs-page": {"title": "Dogs", "body": "Canine friends bark loudly."},
        "fish-page": {"title": "Fish", "body": "Aquatic swimmers glide silently."},
    }
    vectors = {
        "chunks": {
            "cats-page": [[1.0, 0.0, 0.0]],
            "dogs-page": [[0.0, 1.0, 0.0]],
            "fish-page": [[0.0, 0.0, 1.0]],
        },
        "queries": {"purring quadruped": [1.0, 0.0, 0.0]},  # aligns with cats-page
    }
    labels = {"purring quadruped": ["cats-page"]}

    session = bh.make_session()
    bh.seed_corpus(session, corpus, vectors)
    per_query = bh.run_eval(session, labels, vectors, ks=(5,))

    assert per_query[0]["ranked"][0] == "cats-page"
    assert bh.recall_at_k(per_query, 5) == 1.0
