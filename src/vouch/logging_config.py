"""Logging configuration for vouch.

Reads the following environment variables at startup:

  VOUCH_LOG_FORMAT   "text" (default) — human-readable
                     "json"           — one JSON object per log line
  VOUCH_LOG_LEVEL    Any standard level name (default: WARNING)
  VOUCH_LOG_FILE     Optional path — append logs to this file in addition
                     to stderr. Honoured for both text and json formats.

Call configure_logging() once at process startup before any log output.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record.

    Standard fields: time, level, logger, message.
    Any key=value pairs passed via ``extra=`` on the log call are merged in
    at the top level, giving structured context to log consumers.
    """

    _RESERVED = frozenset(logging.LogRecord(
        "", 0, "", 0, "", (), None
    ).__dict__.keys()) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        obj: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge any extra= fields the caller passed in
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                obj[key] = value
        if record.exc_info:
            obj["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(obj, separators=(",", ":"))


class _VouchManagedHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Marker subclass so configure_logging() can find and replace its own
    handlers on repeated calls without touching handlers added by the host
    application or test framework."""


def configure_logging(*, force: bool = False) -> None:
    """Configure the root logger based on VOUCH_LOG_FORMAT.

    Safe to call multiple times — subsequent calls are no-ops unless
    force=True is passed. Call once at process startup before any log output.

    Environment variables honoured:
      VOUCH_LOG_FORMAT  "text" | "json"   (default: "text")
      VOUCH_LOG_LEVEL   any logging level  (default: "WARNING")
      VOUCH_LOG_FILE    filesystem path    (default: unset / stderr only)
    """
    root = logging.getLogger()

    # Remove only our own managed handlers, leave host handlers untouched
    managed = [h for h in root.handlers if isinstance(h, _VouchManagedHandler)]
    if managed and not force:
        return
    for h in managed:
        root.removeHandler(h)
        h.close()

    fmt = os.environ.get("VOUCH_LOG_FORMAT", "text").strip().lower()
    level_name = os.environ.get("VOUCH_LOG_LEVEL", "WARNING").upper()
    level = getattr(logging, level_name, logging.WARNING)

    def _make_formatter() -> logging.Formatter:
        if fmt == "json":
            return _JsonFormatter()
        return logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    # stderr handler (always present)
    stderr_handler = _VouchManagedHandler(sys.stderr)
    stderr_handler.setFormatter(_make_formatter())
    root.addHandler(stderr_handler)

    # optional file handler
    log_file = os.environ.get("VOUCH_LOG_FILE", "").strip()
    if log_file:
        file_handler = _VouchManagedHandler(open(log_file, "a", encoding="utf-8"))  # noqa: SIM115
        file_handler.setFormatter(_make_formatter())
        root.addHandler(file_handler)

    root.setLevel(level)
