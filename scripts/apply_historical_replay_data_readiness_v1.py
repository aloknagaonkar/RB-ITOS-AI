from pathlib import Path

p = Path("backend/market_lab/api.py")
text = p.read_text()

imp = "from .historical_replay_data_api_v1 import router as historical_replay_data_router\n"
if imp not in text:
    marker = "from fastapi import "
    idx = text.find(marker)
    if idx < 0:
        raise SystemExit("FastAPI import anchor not found")
    end = text.find("\n", idx)
    text = text[:end + 1] + imp + text[end + 1:]

if "include_router(historical_replay_data_router)" not in text:
    marker = "    return app"
    if marker not in text:
        raise SystemExit("create_app return anchor not found; inspect backend/market_lab/api.py")
    text = text.replace(
        marker,
        "    app.include_router(historical_replay_data_router)\n" + marker,
        1,
    )

p.write_text(text)
print("Patched API with historical replay data router.")
