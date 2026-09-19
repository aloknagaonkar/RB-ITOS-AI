from pathlib import Path
API=Path("backend/market_lab/historical_replay_operations_api_v1.py")
text=API.read_text(encoding="utf-8")
routes = "\n\n@router.get(\"/historical-oi/built/sessions\")\ndef historical_oi_built_sessions():\n    from .historical_oi_built_source_adapter_v1 import built_inventory\n    return built_inventory()\n\n@router.get(\"/historical-oi/built/session\")\ndef historical_oi_built_session(session_date: str):\n    from fastapi import HTTPException\n    from .historical_oi_built_source_adapter_v1 import build_checkpoint_rows\n    try:\n        return build_checkpoint_rows(session_date)\n    except KeyError as exc:\n        raise HTTPException(status_code=404, detail=str(exc))\n    except ValueError as exc:\n        raise HTTPException(status_code=422, detail=str(exc))\n"
if '@router.get("/historical-oi/built/sessions")' not in text:
    text=text.rstrip()+routes+"\n"
API.write_text(text,encoding="utf-8")
print("Wired built historical OI endpoints.")
