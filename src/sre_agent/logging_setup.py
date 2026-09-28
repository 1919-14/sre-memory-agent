"""Logging configuration.

Every tool call and agent stage logs a single structured line — it doubles as
demo material for the UI activity stream.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

_CONFIGURED = False


class _UnclosedSessionFilter(logging.Filter):
    """Drop the third-party 'Unclosed client session' shutdown warning only."""

    _IGNORED = ("unclosed client session", "unclosed connector")

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        message = record.getMessage().lower()
        return not any(fragment in message for fragment in self._IGNORED)


class JsonLineFormatter(logging.Formatter):
    """One JSON object per line — machine readable, safe to ship to the UI."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Readable terminal output: time, level, short logger, message."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        ts = datetime.now().strftime("%H:%M:%S")
        name = record.name.replace("sre_agent.", "")
        base = f"{ts} {record.levelname:<5} {name:<28} {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_stdout() -> None:
    """Force UTF-8 console output.

    Model output regularly contains non-ASCII punctuation. On a Windows console the
    default cp1252 codec raises UnicodeEncodeError mid-run, which would abort an incident
    while printing its own resolution.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - stream not reconfigurable
            pass


def setup_logging(force: bool = False) -> None:
    global _CONFIGURED
    configure_stdout()
    if _CONFIGURED and not force:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(ConsoleFormatter())
    console.setLevel(level)
    root.addHandler(console)

    if settings.log_to_file:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        log_path: Path = settings.data_dir / "agent.jsonl"
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(JsonLineFormatter())
        file_handler.setLevel(level)
        root.addHandler(file_handler)

    # Third-party noise
    for noisy in ("httpx", "httpcore", "urllib3", "git"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # The Hindsight client uses an internal aiohttp session that its sync `close()` does
    # not always tear down, so Python warns about it during interpreter shutdown. It is a
    # third-party cleanup artifact, not an error in our run, so it is filtered by name
    # rather than by silencing the asyncio logger wholesale.
    logging.getLogger("asyncio").addFilter(_UnclosedSessionFilter())

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name if name.startswith("sre_agent") else f"sre_agent.{name}")
