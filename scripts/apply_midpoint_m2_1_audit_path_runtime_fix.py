#!/usr/bin/env python3
from pathlib import Path

TARGET = Path("backend/market_lab/midpoint_strategy/live_shadow_ui.py")

def main():
    s = TARGET.read_text()
    old = 'def _all_rows(path: Path = AUDIT_PATH) -> list[dict[str, Any]]:\n    return load_audit_jsonl(path) if path.exists() else []\n'
    new = 'def _all_rows(path: Path | None = None) -> list[dict[str, Any]]:\n    resolved = AUDIT_PATH if path is None else path\n    return load_audit_jsonl(resolved) if resolved.exists() else []\n'
    if old not in s:
        if new in s:
            print("PASS: runtime AUDIT_PATH fix already present.")
            return
        raise SystemExit("STOP: expected _all_rows signature not found")
    backup = TARGET.with_suffix(TARGET.suffix + ".pre-m2-1.bak")
    if not backup.exists():
        backup.write_text(s)
    TARGET.write_text(s.replace(old, new, 1))
    print(f"Patched: {TARGET}")
    print("PASS: _all_rows now resolves AUDIT_PATH at call time.")
    print("This restores monkeypatch/test isolation and changes no strategy logic.")

if __name__ == "__main__":
    main()
