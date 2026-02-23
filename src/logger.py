"""
Logging setup for QPSS Middleware.
Creates daily rotating log files in plain text format.
"""

import logging
import os
from datetime import datetime


def setup_logger(log_dir: str) -> logging.Logger:
    """Set up and return the application logger with daily file rotation."""
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("qpss")
    logger.setLevel(logging.DEBUG)

    # Don't add handlers if they already exist (avoids duplicates on re-import)
    if logger.handlers:
        return logger

    # Daily log file: qpss-YYYY-MM-DD.log
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(log_dir, f"qpss-{today}.log")

    # File handler - all messages
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)

    # Console handler - INFO and above
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler.setFormatter(console_fmt)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger
