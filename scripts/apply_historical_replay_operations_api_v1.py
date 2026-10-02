from pathlib import Path
p=Path("backend/market_lab/api.py")
text=p.read_text(encoding="utf-8")
import_line="from .historical_replay_operations_api_v1 import router as historical_replay_operations_router\n"
if import_line not in text:
    marker="def create_app("
    pos=text.find(marker)
    if pos<0: raise SystemExit("SAFE STOP: create_app not found")
    text=text[:pos]+import_line+"\n"+text[pos:]
include_line="    app.include_router(historical_replay_operations_router)\n"
if include_line not in text:
    marker="    # Development uses Vite proxy; built UI can be served by the same local backend.\n"
    pos=text.find(marker)
    if pos<0: raise SystemExit("SAFE STOP: static UI marker not found")
    text=text[:pos]+include_line+text[pos:]
p.write_text(text,encoding="utf-8")
print("Integrated replay operations API router.")
