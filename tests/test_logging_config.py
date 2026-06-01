"""Tests for vouch logging configuration."""
from __future__ import annotations

import json
import logging


def _fresh_configure(
    monkeypatch,
    fmt: str | None,
    level: str | None = None,
    log_file: str | None = None,
):
    """Helper: set env vars and force-reconfigure logging."""
    if fmt is None:
        monkeypatch.delenv("VOUCH_LOG_FORMAT", raising=False)
    else:
        monkeypatch.setenv("VOUCH_LOG_FORMAT", fmt)
    if level is None:
        monkeypatch.delenv("VOUCH_LOG_LEVEL", raising=False)
    else:
        monkeypatch.setenv("VOUCH_LOG_LEVEL", level)
    if log_file is None:
        monkeypatch.delenv("VOUCH_LOG_FILE", raising=False)
    else:
        monkeypatch.setenv("VOUCH_LOG_FILE", log_file)
    import importlib

    import vouch.logging_config as lc
    importlib.reload(lc)
    lc.configure_logging(force=True)
    return lc


def test_json_format_emits_valid_json(monkeypatch, capsys):
    monkeypatch.setenv("VOUCH_LOG_FORMAT", "json")
    from vouch.logging_config import _JsonFormatter
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    record = logging.LogRecord(
        name="vouch.test", level=logging.WARNING,
        pathname="", lineno=0, msg="test message",
        args=(), exc_info=None,
    )
    line = handler.format(record)
    obj = json.loads(line)
    assert obj["level"] == "WARNING"
    assert obj["message"] == "test message"
    assert "time" in obj
    assert "logger" in obj


def test_text_format_is_default(monkeypatch, capsys):
    monkeypatch.delenv("VOUCH_LOG_FORMAT", raising=False)
    from vouch.logging_config import configure_logging
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    old_level = root.level
    try:
        configure_logging(force=True)
        root.warning("hello text")
        captured = capsys.readouterr()
        line = captured.err.strip().splitlines()[-1] if captured.err.strip() else ""
        if line:
            try:
                json.loads(line)
                raise AssertionError("Expected non-JSON output")
            except json.JSONDecodeError:
                pass
    finally:
        root.handlers.clear()
        root.handlers.extend(old_handlers)
        root.setLevel(old_level)


def test_json_extra_fields_are_merged(monkeypatch):
    """Extra fields passed via extra= should appear at top level in JSON output."""
    monkeypatch.setenv("VOUCH_LOG_FORMAT", "json")
    from vouch.logging_config import _JsonFormatter
    formatter = _JsonFormatter()
    record = logging.LogRecord(
        name="vouch.test", level=logging.INFO,
        pathname="", lineno=0, msg="event",
        args=(), exc_info=None,
    )
    record.__dict__["proposal_id"] = "abc-123"
    record.__dict__["action"] = "approve"
    line = formatter.format(record)
    obj = json.loads(line)
    assert obj["proposal_id"] == "abc-123"
    assert obj["action"] == "approve"


def test_vouch_log_level_is_honoured(monkeypatch):
    """VOUCH_LOG_LEVEL should set the root logger level."""
    _fresh_configure(monkeypatch, fmt="text", level="DEBUG")
    root = logging.getLogger()
    assert root.level == logging.DEBUG


def test_vouch_log_file_writes_to_file(monkeypatch, tmp_path):
    """VOUCH_LOG_FILE should append log lines to the specified file."""
    log_path = tmp_path / "vouch.log"
    _fresh_configure(monkeypatch, fmt="json", log_file=str(log_path))
    logger = logging.getLogger("vouch.test_file")
    logger.setLevel(logging.DEBUG)
    logging.getLogger().setLevel(logging.DEBUG)
    logger.warning("file test message")
    content = log_path.read_text()
    assert content.strip(), "Log file should not be empty"
    obj = json.loads(content.strip().splitlines()[-1])
    assert obj["message"] == "file test message"


def test_managed_handler_replaced_on_force(monkeypatch):
    """force=True should replace managed handlers, not stack them."""
    from vouch.logging_config import _VouchManagedHandler, configure_logging
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    old_level = root.level
    try:
        configure_logging(force=True)
        configure_logging(force=True)
        managed = [h for h in root.handlers if isinstance(h, _VouchManagedHandler)]
        assert len(managed) == 1, f"Expected 1 managed handler, got {len(managed)}"
    finally:
        root.handlers.clear()
        root.handlers.extend(old_handlers)
        root.setLevel(old_level)


def test_non_managed_handlers_untouched(monkeypatch):
    """configure_logging should not remove handlers added by the host."""
    from vouch.logging_config import configure_logging
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    old_level = root.level
    host_handler = logging.NullHandler()
    try:
        root.addHandler(host_handler)
        configure_logging(force=True)
        assert host_handler in root.handlers, "Host handler should not be removed"
    finally:
        root.handlers.clear()
        root.handlers.extend(old_handlers)
        root.setLevel(old_level)
