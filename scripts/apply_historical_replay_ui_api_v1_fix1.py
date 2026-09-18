from pathlib import Path

path = Path("backend/market_lab/historical_replay_ui_api_v1.py")
text = path.read_text(encoding="utf-8")

old1 = "def _session_dir(session_date: str, replay_root: Path = REPLAY_ROOT) -> Path:\n"
new1 = (
    "def _session_dir(session_date: str, replay_root: Path | None = None) -> Path:\n"
    "    replay_root = REPLAY_ROOT if replay_root is None else replay_root\n"
)
if old1 not in text and new1.splitlines()[0] not in text:
    raise SystemExit("SAFE STOP: _session_dir signature anchor not found")
text = text.replace(old1, new1)

old2 = "def list_sessions(replay_root: Path = REPLAY_ROOT) -> list[dict[str, Any]]:\n"
new2 = (
    "def list_sessions(replay_root: Path | None = None) -> list[dict[str, Any]]:\n"
    "    replay_root = REPLAY_ROOT if replay_root is None else replay_root\n"
)
if old2 not in text and new2.splitlines()[0] not in text:
    raise SystemExit("SAFE STOP: list_sessions signature anchor not found")
text = text.replace(old2, new2)

path.write_text(text, encoding="utf-8")
print("Patched dynamic REPLAY_ROOT lookup for tests and runtime.")
