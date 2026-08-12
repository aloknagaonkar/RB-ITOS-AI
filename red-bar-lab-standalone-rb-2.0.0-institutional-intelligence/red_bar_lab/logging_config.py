from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
import re
import uuid


SECRET_PATTERN = re.compile(
    r"(?i)(access_token|authorization|client_secret|refresh_token|api_secret)"
    r"\s*[=:]\s*[^,\s]+"
)


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            redacted = SECRET_PATTERN.sub(r"\1=[REDACTED]", message)
            record.msg = redacted
            record.args = ()
        except Exception:
            pass
        return True


def configure_logging(log_root: Path, run_id: str | None = None) -> tuple[logging.Logger, str, Path]:
    run_id = run_id or uuid.uuid4().hex[:6].upper()
    day_root = Path(log_root) / datetime.now().date().isoformat()
    day_root.mkdir(parents=True, exist_ok=True)
    path = day_root / f"run_{run_id}.log"

    logger = logging.getLogger(f"red_bar.{run_id}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s [RB:%(name)s] %(levelname)s %(message)s"
    )
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(formatter)
    handler.addFilter(SecretRedactionFilter())
    logger.addHandler(handler)
    return logger, run_id, path
