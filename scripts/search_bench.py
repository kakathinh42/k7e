"""Print recall@5/@10, MRR, and per-query misses for the retrieval eval corpus.

Offline: reads the committed fixtures + cached vectors, runs the real
HybridSearchProvider over in-memory SQLite. Usage: python scripts/search_bench.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# bench_harness lives in tests/api and is intentionally not a shipped package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests" / "api"))

import bench_harness as bh  # noqa: E402


def main() -> None:
    corpus, labels, vectors = bh.load_fixtures()
    session = bh.make_session()
    bh.seed_corpus(session, corpus, vectors)
    per_query = bh.run_eval(session, labels, vectors)

    r5 = bh.recall_at_k(per_query, 5)
    r10 = bh.recall_at_k(per_query, 10)
    mrr = bh.mrr(per_query)
    print(
        f"queries={len(per_query)}  recall@5={r5:.3f}  recall@10={r10:.3f}  MRR={mrr:.3f}"
    )

    misses = [r for r in per_query if not (set(r["expected"]) & set(r["ranked"][:5]))]
    if misses:
        print(f"\nMISSES (expected not in top-5): {len(misses)}")
        for r in misses:
            print(f"  q={r['query']!r} expected={r['expected']} top5={r['ranked'][:5]}")


if __name__ == "__main__":
    main()
