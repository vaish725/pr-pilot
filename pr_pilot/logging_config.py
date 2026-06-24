import json
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

_request_id: ContextVar[str] = ContextVar('request_id', default='')


def get_request_id() -> str:
    return _request_id.get()


def set_request_id(val: str):
    """Set request_id for the current async context. Returns the reset token."""
    return _request_id.set(val)


def reset_request_id(token) -> None:
    """Reset the request_id ContextVar to its previous value using the token from set_request_id."""
    _request_id.reset(token)


def generate_request_id() -> str:
    return str(uuid.uuid4())


_EXTRA_FIELDS = ('repo', 'pr_number', 'duration_ms', 'error', 'owner', 'status_code')


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj: dict = {
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        rid = get_request_id()
        if rid:
            obj['request_id'] = rid
        for field in _EXTRA_FIELDS:
            val = getattr(record, field, None)
            if val is not None:
                obj[field] = val
        if record.exc_info:
            obj['exception'] = self.formatException(record.exc_info)
        return json.dumps(obj, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Wire a JSON formatter onto the root logger. Idempotent."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
