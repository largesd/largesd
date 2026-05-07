"""JSON logging setup for the debate system."""

import json
import logging
import sys
from datetime import UTC, datetime


class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": datetime.now(UTC).replace(tzinfo=None).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "funcName": record.funcName,
        }
        for attr in ("event_type", "user_id", "snapshot_id", "request_id"):
            if hasattr(record, attr):
                log_obj[attr] = getattr(record, attr)
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)


def _setup_app_logger():
    logger = logging.getLogger("debate_system")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    return logger


app_logger = _setup_app_logger()
