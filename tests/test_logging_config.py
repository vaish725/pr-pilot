"""Tests for structured JSON logging."""
import json
import logging
import threading

import pytest

from pr_pilot.logging_config import (
    JsonFormatter,
    configure_logging,
    generate_request_id,
    get_request_id,
    reset_request_id,
    set_request_id,
)


@pytest.fixture(autouse=True)
def _reset_ctx():
    """Ensure request_id is cleared between tests."""
    token = set_request_id('')
    yield
    reset_request_id(token)


def _make_record(msg='hello', level=logging.INFO, **extra):
    record = logging.LogRecord(
        name='test', level=level, pathname='', lineno=0,
        msg=msg, args=(), exc_info=None,
    )
    for k, v in extra.items():
        setattr(record, k, v)
    return record


def test_json_formatter_basic_fields():
    fmt = JsonFormatter()
    out = json.loads(fmt.format(_make_record('hi')))
    assert out['message'] == 'hi'
    assert out['level'] == 'INFO'
    assert out['logger'] == 'test'
    assert 'timestamp' in out
    assert out['timestamp'].endswith('+00:00') or out['timestamp'].endswith('Z') or '+' in out['timestamp']


def test_request_id_included_when_set():
    fmt = JsonFormatter()
    set_request_id('abc-123')
    out = json.loads(fmt.format(_make_record('msg')))
    assert out['request_id'] == 'abc-123'


def test_request_id_omitted_when_empty():
    fmt = JsonFormatter()
    set_request_id('')
    out = json.loads(fmt.format(_make_record('msg')))
    assert 'request_id' not in out


def test_extra_fields_included():
    fmt = JsonFormatter()
    record = _make_record('done', repo='acme/api', pr_number=42, duration_ms=150.3)
    out = json.loads(fmt.format(record))
    assert out['repo'] == 'acme/api'
    assert out['pr_number'] == 42
    assert out['duration_ms'] == 150.3


def test_error_field_included():
    fmt = JsonFormatter()
    record = _make_record('fail', error='connection refused')
    out = json.loads(fmt.format(record))
    assert out['error'] == 'connection refused'


def test_exception_info_serialized():
    fmt = JsonFormatter()
    try:
        raise ValueError('boom')
    except ValueError:
        import sys
        record = logging.LogRecord(
            name='test', level=logging.ERROR, pathname='', lineno=0,
            msg='err', args=(), exc_info=sys.exc_info(),
        )
    out = json.loads(fmt.format(record))
    assert 'exception' in out
    assert 'ValueError' in out['exception']


def test_generate_request_id_is_unique():
    ids = {generate_request_id() for _ in range(100)}
    assert len(ids) == 100


def test_request_id_isolated_per_thread():
    import time
    results = {}

    def worker(name, val):
        set_request_id(val)
        time.sleep(0.01)
        results[name] = get_request_id()

    t1 = threading.Thread(target=worker, args=('t1', 'id-t1'))
    t2 = threading.Thread(target=worker, args=('t2', 'id-t2'))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert results['t1'] == 'id-t1'
    assert results['t2'] == 'id-t2'


def test_configure_logging_installs_json_formatter(capfd):
    configure_logging()
    logging.getLogger('cfg_test').info('structured log', extra={'repo': 'x/y'})
    captured = capfd.readouterr()
    out = json.loads(captured.err.strip())
    assert out['message'] == 'structured log'
    assert out['repo'] == 'x/y'
