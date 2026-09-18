from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

MODULES = (
    "market_lab.historical_replay_operations_worker_v1",
    "market_lab.historical_replay_operations_api_v1",
    "market_lab.historical_replay_ui_api_v1",
)

FRONTEND_FILES = (
    "frontend/src/historicalReplay.tsx",
    "frontend/src/historicalReplayOperations.tsx",
)

OUTPUT = Path("data/live-observation/replay/hardening-compat-probe-v1.json")


def _module_report(name: str) -> dict[str, Any]:
    try:
        module = __import__(name, fromlist=["*"])
    except Exception as exc:
        return {
            "error": type(exc).__name__,
            "detail": str(exc),
        }

    result: dict[str, Any] = {
        "file": getattr(module, "__file__", None),
        "callables": {},
        "source": {},
    }

    for symbol in (
        "run_job",
        "main",
        "list_jobs",
        "get_job",
        "run_replay",
        "download_missing",
        "readiness_endpoint",
        "router",
    ):
        obj = getattr(module, symbol, None)
        if obj is None:
            continue
        try:
            result["callables"][symbol] = str(inspect.signature(obj))
        except Exception:
            result["callables"][symbol] = None
        if callable(obj):
            try:
                result["source"][symbol] = inspect.getsource(obj)
            except Exception:
                pass

    try:
        result["module_source"] = inspect.getsource(module)
    except Exception:
        pass

    return result


def _frontend_report(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"exists": False}
    text = p.read_text(encoding="utf-8")
    return {
        "exists": True,
        "bytes": p.stat().st_size,
        "text": text,
    }


def build_report() -> dict[str, Any]:
    report = {
        "model": "HISTORICAL_REPLAY_HARDENING_COMPAT_PROBE_V1",
        "modules": {name: _module_report(name) for name in MODULES},
        "frontend": {path: _frontend_report(path) for path in FRONTEND_FILES},
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    report = build_report()
    summary = {
        "model": report["model"],
        "output": str(OUTPUT),
        "modules": {
            name: {
                "file": value.get("file"),
                "error": value.get("error"),
                "callables": value.get("callables"),
            }
            for name, value in report["modules"].items()
        },
        "frontend": {
            name: {
                "exists": value.get("exists"),
                "bytes": value.get("bytes"),
            }
            for name, value in report["frontend"].items()
        },
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
