#!/usr/bin/env python3
"""Read-only introspection of the existing shared Hilega live runtime.

This does not start workers and does not call broker APIs.
Its output is used to wire M3B without guessing method signatures.
"""
from __future__ import annotations

import importlib
import inspect


TARGETS = [
    ("market_lab.live_shadow_worker_v1", None),
    ("market_lab.upstox_live_shadow_sources_v1", "UpstoxLiveShadowSourcesV1"),
    ("market_lab.hilega_milega_live_shadow_v1", "HilegaMilegaLiveShadowCoordinatorV1"),
    ("market_lab.hilega_directional_live_shadow_v1", "HilegaDirectionalLiveShadowCoordinatorV1"),
]


def public_methods(cls):
    out = []
    for name, value in inspect.getmembers(cls):
        if name.startswith("_"):
            continue
        if inspect.isfunction(value) or inspect.ismethod(value):
            try:
                sig = str(inspect.signature(value))
            except Exception:
                sig = "(signature unavailable)"
            out.append((name, sig))
    return out


def main():
    print("MIDPOINT M3B SHARED-RUNTIME PREFLIGHT")
    print("=" * 100)
    for module_name, class_name in TARGETS:
        print(f"\nMODULE {module_name}")
        module = importlib.import_module(module_name)
        print(f"FILE {inspect.getsourcefile(module)}")
        if class_name:
            cls = getattr(module, class_name)
            try:
                print(f"CLASS {class_name}{inspect.signature(cls)}")
            except Exception:
                print(f"CLASS {class_name}")
            for name, sig in public_methods(cls):
                print(f"  {name}{sig}")
        else:
            for name in ("main","run","floor_5m"):
                value = getattr(module, name, None)
                if callable(value):
                    try:
                        print(f"  {name}{inspect.signature(value)}")
                    except Exception:
                        print(f"  {name}")

    print("\nPASS: read-only introspection only; no workers or broker calls started")


if __name__ == "__main__":
    main()
