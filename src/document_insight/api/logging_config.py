"""Server logging configuration with an always-present correlation field."""

import logging
from collections.abc import Callable
from typing import Any

from document_insight.api.middleware.correlation_id import get_correlation_id

_record_factory_installed = False


class CorrelationIdFormatter(logging.Formatter):
    """Prefix an existing formatter's output with its correlation identifier."""

    def __init__(self, delegate: logging.Formatter) -> None:
        super().__init__()
        self._delegate = delegate

    def format(self, record: logging.LogRecord) -> str:
        """Render the original log format with a stable correlation field."""
        correlation_id = record.__dict__.get("correlation_id", "-")
        return f"correlation_id={correlation_id} {self._delegate.format(record)}"


def configure_server_logging() -> None:
    """Inject correlation IDs into all log records and configured server handlers."""
    _install_record_factory()
    handlers: set[logging.Handler] = set(logging.getLogger().handlers)
    for configured_logger in logging.Logger.manager.loggerDict.values():
        if isinstance(configured_logger, logging.Logger):
            handlers.update(configured_logger.handlers)

    for handler in handlers:
        if not isinstance(handler.formatter, CorrelationIdFormatter):
            handler.setFormatter(CorrelationIdFormatter(handler.formatter or logging.Formatter()))


def _install_record_factory() -> None:
    global _record_factory_installed
    if _record_factory_installed:
        return

    previous_factory: Callable[..., logging.LogRecord] = logging.getLogRecordFactory()

    # The stdlib record-factory hook is variadic and intentionally typed at this boundary.
    def correlation_record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous_factory(*args, **kwargs)
        record.__dict__["correlation_id"] = get_correlation_id() or "-"
        return record

    logging.setLogRecordFactory(correlation_record_factory)
    _record_factory_installed = True
