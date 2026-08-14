import pytest
from k7e_api.source_tier import resolve_source_tier


def test_explicit_tier_wins_case_insensitive():
    assert resolve_source_tier("manual_upload", "B") == "B"
    assert resolve_source_tier("zoom", "a") == "A"


def test_invalid_explicit_tier_raises():
    with pytest.raises(ValueError):
        resolve_source_tier("manual_upload", "C")


def test_default_map_by_source_system():
    assert resolve_source_tier("zoom") == "B"
    assert resolve_source_tier("slack") == "B"
    assert resolve_source_tier("confluence") == "A"


def test_unknown_system_defaults_to_a():
    assert resolve_source_tier("something-new") == "A"


def test_empty_explicit_falls_back_to_default():
    assert resolve_source_tier("zoom", "") == "B"
    assert resolve_source_tier("manual_upload", None) == "A"
