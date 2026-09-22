"""Shared fixtures."""

import logging

import pytest


@pytest.fixture(autouse=True, scope="session")
def _no_real_log_file():
    """Keep the suite out of ~/.whisper_dictate/logs.

    gui.py calls setup_logging() at import, which opens the real log; every
    run of the suite was leaving test-only lines in it, including a fake
    "held the hook thread for 200 ms" that reads like a real measurement.
    """
    logger = logging.getLogger("whisper_dictate")
    for handler in [h for h in logger.handlers if isinstance(h, logging.FileHandler)]:
        logger.removeHandler(handler)
        handler.close()
    yield
