from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
from typing import Any

MODULES = [
    "market_lab.live_shadow_production_wiring_v1",
    "market_lab.live_observational_shadow_runtime_adapter_v1",
    "market_lab.live_normalized_feature_producer_v1",
    "market_lab.live_futures_source_v1",
    "market_lab.live_option_minute_source_v1",
    "market_lab.live_shadow_step_audit_v1",
    "market_lab.live_observational_shadow_v1",
    "market_lab.live_shadow_worker_v1",
]


def _sig(obj: Any) -> str:
    try:
        return str(inspect.signature(obj))
    except Exception as exc:
        return f"<unavailable: {type(exc).__name__}: {exc}>"


def _public_methods(cls: type) -> dict[str, str]:
    out = {}
    for name, value in inspect.getmembers(cls):
        if name.startswith("_"):
            continue
        if inspect.isfunction(value) or inspect.ismethod(value):
            out[name] = _sig(value)
    return out


def _class_report(module) -> dict[str, Any]:
    result = {}
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if obj.__module__ != module.__name__:
            continue
        result[name] = {
            "signature": _sig(obj),
            "methods": _public_methods(obj),
        }
    return result


class CallVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.self_attr_calls: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        fn = node.func
        if (
            isinstance(fn, ast.Attribute)
            and isinstance(fn.value, ast.Attribute)
            and isinstance(fn.value.value, ast.Name)
            and fn.value.value.id == "self"
        ):
            self.self_attr_calls.add(f"self.{fn.value.attr}.{fn.attr}")
        self.generic_visit(node)


def _market_source_calls(module) -> list[str]:
    source = inspect.getsource(module)
    tree = ast.parse(source)
    visitor = CallVisitor()
    visitor.visit(tree)
    return sorted(
        x for x in visitor.self_attr_calls
        if "source" in x.lower() or "market" in x.lower()
    )


def _coordinator_source_excerpt(module) -> str | None:
    cls = getattr(module, "LiveShadowProductionCoordinatorV1", None)
    if cls is None:
        return None
    src = inspect.getsource(cls)
    # Keep report readable while preserving all coordinator details.
    return src


def build_report() -> dict[str, Any]:
    import importlib

    result: dict[str, Any] = {
        "model": "HISTORICAL_REPLAY_COMPAT_PROBE_V1",
        "modules": {},
    }

    for module_name in MODULES:
        try:
            module = importlib.import_module(module_name)
            entry = {
                "file": inspect.getsourcefile(module),
                "classes": _class_report(module),
            }
            if module_name.endswith("live_shadow_production_wiring_v1"):
                entry["market_source_calls"] = _market_source_calls(module)
                entry["coordinator_source"] = _coordinator_source_excerpt(module)
            result["modules"][module_name] = entry
        except Exception as exc:
            result["modules"][module_name] = {
                "error": f"{type(exc).__name__}: {exc}",
            }

    return result


def main() -> None:
    report = build_report()
    out = Path("data/live-observation/replay/compat-probe-v1.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    print(f"\nWROTE {out}")


if __name__ == "__main__":
    main()
