import logging

from k7e_api import config, logging_setup


def test_configure_logging_respects_log_level(monkeypatch):
    config.get_settings.cache_clear()
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    logging_setup.configure_logging()
    assert logging.getLogger().level == logging.DEBUG
    config.get_settings.cache_clear()
    logging_setup.configure_logging()  # restore INFO default
