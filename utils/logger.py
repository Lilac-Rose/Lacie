import logging
import sys


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger for the given module name.

    Args:
        name: The module name, typically __name__ from the calling module.

    Returns:
        A configured logging.Logger instance.
    """
    logger = logging.getLogger(name)
    return logger


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the root logger with a console handler.

    Call this once at bot startup (in bot.py) before any other logging.

    Args:
        level: The logging level to use. Defaults to INFO.
    """
    root = logging.getLogger()
    root.setLevel(level)

    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        formatter = logging.Formatter(
            "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)
