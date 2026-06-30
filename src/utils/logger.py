"""
src/utils/logger.py
=====================
Configures the root "platform" logger for the entire project.

Call setup_logging() once at the start of main.py.
All collectors automatically use child loggers (platform.world_bank, etc.)
that inherit this configuration.

Log format:  2026-06-22 17:30:00 | INFO  | platform.world_bank | message
Output    :  Console (stdout) + logs/platform.log (rotating, max 5 MB × 3 files)
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_dir: str = "logs", level: str = "INFO") -> None:
    """
    Configure the root platform logger.
    Call once at application startup (in main.py).

    Parameters
    ----------
    log_dir : str   — directory for the rotating log file
    level   : str   — log level name: DEBUG, INFO, WARNING, ERROR
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, level.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)

    # Rotating file handler (5 MB × 3 backups = 15 MB max)
    file_handler = RotatingFileHandler(
        filename=log_path / "platform.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    # Attach to the "platform" logger — all child loggers inherit from it
    root_logger = logging.getLogger("platform")
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(console)
    root_logger.addHandler(file_handler)
    root_logger.propagate = False
