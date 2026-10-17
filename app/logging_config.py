import logging

from .security import redact_sensitive


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(redact_sensitive(str(arg)) if isinstance(arg, str) else arg for arg in record.args)
        if isinstance(record.msg, str):
            record.msg = redact_sensitive(record.msg)
        return True


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    sensitive_filter = SensitiveDataFilter()
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "app"):
        logger = logging.getLogger(name)
        logger.addFilter(sensitive_filter)
