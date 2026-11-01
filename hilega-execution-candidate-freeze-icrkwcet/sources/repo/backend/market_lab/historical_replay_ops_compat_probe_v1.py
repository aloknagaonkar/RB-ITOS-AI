from __future__ import annotations

import argparse
import importlib
import inspect
import json
from pathlib import Path
from typing import Any

MODEL = "HISTORICAL_REPLAY_OPS_COMPAT_PROBE_V1"

MODULES = (
    "market_lab.historical_replay_data_api_v1",
    "market_lab.historical_replay_data_v1",
    "market_lab.historical_replay_day_v1_1",
    "market_lab.api",
)


def _safe_signature(obj: Any) -> str | None:
    try:
        return str(inspect.signature(obj))
    except (TypeError, ValueError):
        return None


def _public_callables(module) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, value in vars(module).items():
        if name.startswith("_"):
            continue
        if inspect.isfunction(value) or inspect.isclass(value):
            sig = _safe_signature(value)
            if sig is not None:
                result[name] = sig
    return dict(sorted(result.items()))


def _router_routes(module) -> list[dict[str, Any]]:
    router = getattr(module, "router", None)
    if router is None:
        return []

    rows = []
    for route in getattr(router, "routes", []):
        rows.append({
            "path": getattr(route, "path", None),
            "name": getattr(route, "name", None),
            "methods": sorted(getattr(route, "methods", []) or []),
            "endpoint_signature": _safe_signature(getattr(route, "endpoint", None)),
        })
    return rows


def _app_routes(module) -> list[dict[str, Any]]:
    app = getattr(module, "app", None)
    if app is None:
        return []

    rows = []
    for route in getattr(app, "routes", []):
        path = getattr(route, "path", None)
        if not path or "replay" not in path.lower():
            continue
        rows.append({
            "path": path,
            "name": getattr(route, "name", None),
            "methods": sorted(getattr(route, "methods", []) or []),
            "endpoint_signature": _safe_signature(getattr(route, "endpoint", None)),
        })
    return rows


def build_report() -> dict[str, Any]:
    report: dict[str, Any] = {
        "model": MODEL,
        "modules": {},
    }

    for module_name in MODULES:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            report["modules"][module_name] = {
                "error": f"{type(exc).__name__}: {exc}",
            }
            continue

        entry: dict[str, Any] = {
            "file": getattr(module, "__file__", None),
            "callables": _public_callables(module),
            "router_routes": _router_routes(module),
            "app_replay_routes": _app_routes(module),
        }

        main = getattr(module, "_main", None)
        if main is not None:
            try:
                entry["main_source"] = inspect.getsource(main)
            except (OSError, TypeError):
                entry["main_source"] = None

        report["modules"][module_name] = entry

    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="data/live-observation/replay/ops-compat-probe-v1.json",
    )
    args = parser.parse_args()

    report = build_report()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
