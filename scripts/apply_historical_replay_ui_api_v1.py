from pathlib import Path

p = Path("backend/market_lab/api.py")
text = p.read_text(encoding="utf-8")

import_line = "from .historical_replay_ui_api_v1 import router as historical_replay_router\n"
if import_line not in text:
    # Insert after future/import block, before first local app code.
    lines = text.splitlines(keepends=True)
    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith("from .") or line.startswith("from fastapi") or line.startswith("import "):
            insert_at = i + 1
    lines.insert(insert_at, import_line)
    text = "".join(lines)

include_line = "    app.include_router(historical_replay_router)\n"
if include_line not in text:
    marker = "    return app"
    pos = text.rfind(marker)
    if pos < 0:
        raise SystemExit(
            "SAFE STOP: could not find final '    return app' in backend/market_lab/api.py. "
            "No router registration was applied."
        )
    text = text[:pos] + include_line + text[pos:]

p.write_text(text, encoding="utf-8")
print("Patched backend/market_lab/api.py with Historical Replay API router.")
