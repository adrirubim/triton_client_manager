"""Centralized logging configuration for Triton Client Manager."""

import logging
import sys


class ContextFilter(logging.Filter):
    """Ensure correlation fields are always present on log records.

    This lets us include client / job identifiers in the log format safely,
    even when a particular call site does not supply them via ``extra=``.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[type-arg]
        for attr in ("client_uuid", "job_id", "job_type", "correlation_id"):
            if not hasattr(record, attr):
                setattr(record, attr, "-")
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logger with a consistent, correlation-friendly format."""
    logging.basicConfig(
        level=level,
        format=(
            "%(asctime)s [%(name)s] %(levelname)s "
            "[uuid=%(client_uuid)s job=%(job_id)s type=%(job_type)s]: %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )

    root_logger = logging.getLogger()
    # Attach the filter to handlers (not only the logger) so the default fields
    # are present regardless of logger propagation settings.
    context_filter = ContextFilter()
    root_logger.addFilter(context_filter)
    for handler in root_logger.handlers:
        handler.addFilter(context_filter)

    # Reduce noise from third-party libs
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
