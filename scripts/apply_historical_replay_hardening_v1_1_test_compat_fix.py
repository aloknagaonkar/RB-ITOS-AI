from pathlib import Path

PATH = Path("backend/market_lab/historical_replay_operations_api_v1.py")
text = PATH.read_text(encoding="utf-8")

old = '    launched = {**initial, "launcher_pid":process.pid,\n                "stdout_log":str(stdout_path),"stderr_log":str(stderr_path)}\n'
new = '    launched = {**initial, "launcher_pid":getattr(process, "pid", None),\n                "stdout_log":str(stdout_path),"stderr_log":str(stderr_path)}\n'

if new in text:
    print("Historical Replay hardening test-compat fix already applied.")
elif old in text:
    PATH.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("Applied launcher_pid compatibility fix.")
else:
    raise SystemExit(
        "Safe-stop: expected launched={... process.pid ...} block not found; no file modified."
    )
