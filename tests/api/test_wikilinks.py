"""Tests for the [[wikilink]] target parser."""

from __future__ import annotations

from k7e_api.wikilinks import extract_wikilink_targets


def test_extracts_simple_targets():
    md = "See [[Card Apply Workflow]] and [[Refunds]]."
    assert extract_wikilink_targets(md) == ["Card Apply Workflow", "Refunds"]


def test_drops_alias_after_pipe():
    md = "Read [[card-apply-workflow|the apply guide]] now."
    assert extract_wikilink_targets(md) == ["card-apply-workflow"]


def test_dedupes_case_insensitively_keeping_first_spelling():
    md = "[[Refunds]] ... [[refunds]] ... [[REFUNDS]]"
    assert extract_wikilink_targets(md) == ["Refunds"]


def test_strips_surrounding_whitespace():
    assert extract_wikilink_targets("[[  Spaced Out  ]]") == ["Spaced Out"]


def test_ignores_empty_and_malformed():
    assert extract_wikilink_targets("[[]] [[ ]] [single] normal text") == []


def test_handles_none_and_empty():
    assert extract_wikilink_targets("") == []
    assert extract_wikilink_targets(None) == []
