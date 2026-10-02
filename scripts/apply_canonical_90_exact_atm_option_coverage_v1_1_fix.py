from pathlib import Path

P = Path("backend/market_lab/canonical_90_exact_atm_option_coverage_v1.py")
if not P.exists():
    raise SystemExit("Safe-stop: coverage gate module not found")

text = P.read_text(encoding="utf-8")

old_keys = '''        keys: dict[tuple[str, str], set[str]] = {}
        for row in file_rows:
            entry = _dt(row["entry_timestamp"])
            expected = {
                _iso_minute(entry + timedelta(minutes=i))
                for i in range(16)  # entry bar plus exact +1 ... +15 bars
            }
            keys[(row["session_date"], row["instrument_key"])] = expected
'''

new_keys = '''        # Multiple eligible events can reuse the same exact option contract in
        # the same session. Build a UNION of timestamps needed for reading the
        # source file, but evaluate each event against its own 16-minute window.
        keys: dict[tuple[str, str], set[str]] = defaultdict(set)
        for row in file_rows:
            entry = _dt(row["entry_timestamp"])
            expected = {
                _iso_minute(entry + timedelta(minutes=i))
                for i in range(16)  # entry bar plus exact +1 ... +15 bars
            }
            keys[(row["session_date"], row["instrument_key"])].update(expected)
'''

if old_keys not in text:
    raise SystemExit("Safe-stop: expected key-building block not found")
text = text.replace(old_keys, new_keys, 1)

old_eval = '''        for row in file_rows:
            key = (row["session_date"], row["instrument_key"])
            entry = row["entry_timestamp"]
            expected = sorted(keys[key])
            actual = seen.get(key, {})

            if entry not in actual:
                row["coverage_status"] = "MISSING_ENTRY_MINUTE"
                row["missing_timestamps"] = [entry]
                continue
'''

new_eval = '''        for row in file_rows:
            key = (row["session_date"], row["instrument_key"])
            entry = row["entry_timestamp"]
            entry_dt = _dt(entry)
            expected = sorted(
                _iso_minute(entry_dt + timedelta(minutes=i))
                for i in range(16)
            )
            actual = seen.get(key, {})

            if entry not in actual:
                row["coverage_status"] = "MISSING_ENTRY_MINUTE"
                row["missing_timestamps"] = [entry]
                continue
'''

if old_eval not in text:
    raise SystemExit("Safe-stop: expected per-event evaluation block not found")
text = text.replace(old_eval, new_eval, 1)

old_missing = '''            missing_ts = [t for t in expected if t not in actual]
            if missing_ts:
                row["coverage_status"] = "INCOMPLETE_15M_PATH"
                row["entry_open"] = entry_open
                row["path_rows_available"] = len(actual)
                row["missing_timestamps"] = missing_ts
                continue
'''

new_missing = '''            missing_ts = [t for t in expected if t not in actual]
            if missing_ts:
                # NSE option minute bars for the regular session end with the
                # 15:29 bar. If every missing timestamp is 15:30 or later on
                # the same session date, this is deterministic session-end
                # censoring rather than a data gap.
                missing_dt = [_dt(t) for t in missing_ts]
                session_end_censored = all(
                    t.date().isoformat() == row["session_date"]
                    and (t.hour, t.minute) >= (15, 30)
                    for t in missing_dt
                )
                row["coverage_status"] = (
                    "SESSION_END_CENSORED"
                    if session_end_censored
                    else "INCOMPLETE_15M_PATH"
                )
                row["entry_open"] = entry_open
                row["path_rows_available"] = sum(
                    1 for t in expected if t in actual
                )
                row["missing_timestamps"] = missing_ts
                continue
'''

if old_missing not in text:
    raise SystemExit("Safe-stop: expected missing-path block not found")
text = text.replace(old_missing, new_missing, 1)

needle = '"path_requirement": "entry minute through entry+15 minutes inclusive",'
replacement = (
    '"path_requirement": "entry minute through entry+15 minutes inclusive",\n'
    '            "session_end_censoring": "missing timestamps only at 15:30 or later are classified SESSION_END_CENSORED",'
)
if needle in text and "session_end_censoring" not in text:
    text = text.replace(needle, replacement, 1)

P.write_text(text, encoding="utf-8")
print("Patched shared-contract timestamp union bug and session-end censoring classification.")
