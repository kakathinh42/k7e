"""Backfill knobs exist with sane defaults."""

from k7e_api.config import Settings


def test_backfill_settings_defaults():
    s = Settings()
    assert s.embed_backfill_batch_size == 100
    assert s.embed_backfill_interval_seconds == 120
