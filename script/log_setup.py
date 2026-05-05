"""
Configuration logging globale (stderr).

Usage : appeler `setup_logging()` une fois au demarrage de main(). Les
modules utilisent ensuite `logger = logging.getLogger(__name__)`.
"""
import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """Initialise le logger racine. Idempotent."""
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(level)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root.addHandler(handler)
