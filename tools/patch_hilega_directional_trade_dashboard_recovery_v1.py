from pathlib import Path

path = Path("backend/market_lab/hilega_directional_trade_dashboard_v1.py")
text = path.read_text(encoding="utf-8")
original = text

old = 'if direction is None or kind not in {"START", "ENTRY_RETRY", "UPDATE", "EXIT", "EXIT_RETRY"}:'
new = 'if direction is None or kind not in {"START", "ENTRY_RETRY", "UPDATE", "EXIT", "EXIT_RETRY", "RECOVERY"}:'
if old not in text:
    raise SystemExit("PATCH_ANCHOR_1_NOT_FOUND")
text = text.replace(old, new, 1)

old = '''        closed_events = [
            e for e in events
            if e[3].get("status") == "CLOSED" and e[1] in {"EXIT", "EXIT_RETRY"}
        ]
'''
new = '''        recovery_events = [
            e for e in events
            if e[3].get("status") == "CLOSED" and e[1] == "RECOVERY"
        ]
        closed_events = [
            e for e in events
            if e[3].get("status") == "CLOSED" and e[1] in {"EXIT", "EXIT_RETRY", "RECOVERY"}
        ]
'''
if old not in text:
    raise SystemExit("PATCH_ANCHOR_2_NOT_FOUND")
text = text.replace(old, new, 1)

old = '        entry = active_events[0][3] if active_events else None\n'
new = '''        entry = (
            active_events[0][3]
            if active_events
            else recovery_events[-1][3]
            if recovery_events
            else None
        )
'''
if old not in text:
    raise SystemExit("PATCH_ANCHOR_3_NOT_FOUND")
text = text.replace(old, new, 1)

backup = path.with_suffix(path.suffix + ".pre-recovery-dashboard.bak")
if not backup.exists():
    backup.write_text(original, encoding="utf-8")

path.write_text(text, encoding="utf-8")
print("PATCHED:", path)
print("BACKUP :", backup)
