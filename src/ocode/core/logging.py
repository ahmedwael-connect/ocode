"""Logging setup: console + rotating file in ~/.local/state/ocode/ocode.log."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def state_dir() -> Path:
    return Path.home() / ".local" / "state" / "ocode"


def setup_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("ocode")
    if logger.handlers:
        logger.setLevel(level.upper())
        return logger
    logger.setLevel(level.upper())
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    logger.addHandler(console)

    try:
        d = state_dir()
        d.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(d / "ocode.log", encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        pass
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"ocode.{name}")
