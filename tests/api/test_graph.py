import math

from k7e_api.graph import cosine, page_centroid, top_k_neighbors


def test_page_centroid_is_normalized_mean():
    c = page_centroid([[2.0, 0.0], [0.0, 0.0]])
    assert math.isclose(math.sqrt(sum(x * x for x in c)), 1.0, rel_tol=1e-9)
    assert page_centroid([]) == []


def test_top_k_neighbors_threshold_and_order():
    target = [1.0, 0.0]
    cands = [("near", [0.9, 0.1]), ("far", [0.0, 1.0]), ("mid", [0.7, 0.7])]
    out = top_k_neighbors(target, cands, k=2, min_sim=0.5)
    ids = [i for i, _ in out]
    assert ids[0] == "near"
    assert "far" not in ids  # below threshold
    assert len(out) <= 2
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
