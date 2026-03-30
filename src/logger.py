"""
Logging setup for QPSS Middleware.
Creates daily rotating log files in plain text format.
"""

import logging
import os
from datetime import datetime


def setup_logger(log_dir: str) -> logging.Logger:
    """Set up and return the application logger with daily file rotation.

    Safe to call multiple times from a long-running process (e.g. Streamlit):
    - If today's FileHandler is already attached, returns immediately.
    - If a stale FileHandler from a previous day is attached, closes it and
      opens a new one for today before returning.
    """
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("qpss")
    logger.setLevel(logging.DEBUG)

    today = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.abspath(os.path.join(log_dir, f"qpss-{today}.log"))

    # Remove any FileHandler that isn't for today's file.
    # Covers the case where the process started on a previous day and kept running.
    for h in list(logger.handlers):
        if isinstance(h, logging.FileHandler):
            if h.baseFilename == log_file:
                return logger  # Already configured correctly for today.
            h.close()
            logger.removeHandler(h)

    # Add today's FileHandler.
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(file_handler)

    # Add a console StreamHandler only if none exists yet.
    # Uses exact type check (not isinstance) so that FileHandler subclasses and
    # StreamlitLogHandler (which is a plain Handler, not a StreamHandler) are
    # not mistaken for a console handler.
    if not any(type(h) is logging.StreamHandler for h in logger.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%H:%M:%S",
        ))
        logger.addHandler(console_handler)

    return logger
