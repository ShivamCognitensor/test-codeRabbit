from __future__ import annotations

import logging
import sys
import structlog
from app.core.config import get_settings

def configure_logging() -> None:
    """
    Configure the root Python logger and initialize structlog according to application settings.
    
    This function resets the root logger, attaches a stdout stream handler, sets the logger level from configuration, and configures structlog processors and renderer selection (JSON vs console) based on the application's settings.
    """
    settings = get_settings()

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(settings.log_level.upper())

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("%(message)s")
    handler.setFormatter(formatter)
    root.addHandler(handler)

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if settings.log_json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(root.level),
        cache_logger_on_first_use=True,
    )

def get_logger(name: str):
    """
    Retrieve a structlog logger bound to the specified name.
    
    Parameters:
        name (str): The logger name or namespace to retrieve.
    
    Returns:
        structlog.BoundLogger: A structlog logger bound to the given name.
    """
    return structlog.get_logger(name)
