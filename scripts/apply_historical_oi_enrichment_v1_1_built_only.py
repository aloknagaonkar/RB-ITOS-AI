from pathlib import Path

P = Path("backend/market_lab/historical_oi_enrichment_v1.py")
if not P.exists(): raise SystemExit("Safe-stop: module not found")
text = P.read_text(encoding="utf-8")

old = 'def _load_canonical(path: Path, session_date: str) -> list[dict[str, Any]]:\n    with path.open(newline="", encoding="utf-8-sig") as f:\n        rows = [dict(r) for r in csv.DictReader(f) if r.get("session_date") == session_date]\n    if not rows:\n        raise ValueError(f"No canonical rows for {session_date}")\n    return rows\n'
new = 'def _load_canonical(path: Path, session_date: str) -> list[dict[str, Any]]:\n    if not path.exists():\n        return []\n    with path.open(newline="", encoding="utf-8-sig") as f:\n        return [dict(r) for r in csv.DictReader(f) if r.get("session_date") == session_date]\n'
if old in text: text = text.replace(old,new,1)

if "def _built_checkpoint_rows(" not in text:
    marker = "def enrich_session(\n"
    if marker not in text: raise SystemExit("Safe-stop: enrich_session marker not found")
    helper = 'def _built_checkpoint_rows(built_session: dict[str, Any], session_date: str) -> list[dict[str, Any]]:\n    rows = built_session.get("rows") or []\n    by_ts = _index_rows(rows)\n    output = []\n    from datetime import timedelta\n    start = datetime.fromisoformat(f"{session_date}T09:20:00+05:30")\n    end = datetime.fromisoformat(f"{session_date}T15:25:00+05:30")\n    t = start\n    while t <= end:\n        ts = t.isoformat()\n        at = by_ts.get(ts)\n        if at:\n            vals = list(at.values())\n            atms = {float(r["moving_atm"]) for r in vals if r.get("moving_atm") is not None}\n            spots = {float(r["spot"]) for r in vals if r.get("spot") is not None}\n            if len(atms) != 1: raise ValueError(f"Ambiguous moving ATM at {ts}: {sorted(atms)}")\n            if len(spots) != 1: raise ValueError(f"Ambiguous spot at {ts}: {sorted(spots)}")\n            moving_atm = next(iter(atms))\n            spot = next(iter(spots))\n            atm_row = at.get(moving_atm) or {}\n            output.append({"block":"BUILT_ONLY","source":"DOWNLOADED_ENRICHMENT","session_date":session_date,"time":t.strftime("%H:%M"),"timestamp":ts,"spot":spot,"moving_atm":moving_atm,"fixed_atm":None,"ce_state":atm_row.get("ce_5m_state") or "UNAVAILABLE","pe_state":atm_row.get("pe_5m_state") or "UNAVAILABLE","atm_ce_price_pct":atm_row.get("ce_5m_premium_change_pct"),"atm_pe_price_pct":atm_row.get("pe_5m_premium_change_pct"),"pattern_family":None,"forward_5m_points":None,"forward_10m_points":None,"forward_15m_points":None})\n        t += timedelta(minutes=5)\n    if not output: raise ValueError(f"Built source contains no exact 5-minute checkpoints for {session_date}")\n    return output\n\n\n'
    text = text.replace(marker, helper + marker, 1)

needle = '    built_rows = built_session.get("rows") or []\n    by_ts = _index_rows(built_rows)\n    interval = _strike_interval(built_session)\n\n    canonical_by_time = {str(r.get("time")): r for r in canonical_rows}\n'
repl = '    built_rows = built_session.get("rows") or []\n    by_ts = _index_rows(built_rows)\n    interval = _strike_interval(built_session)\n\n    source_mode = "CANONICAL_ENRICHMENT"\n    if not canonical_rows:\n        canonical_rows = _built_checkpoint_rows(built_session, session_date)\n        source_mode = "BUILT_ONLY_ENRICHMENT"\n\n    canonical_by_time = {str(r.get("time")): r for r in canonical_rows}\n'
if needle in text: text = text.replace(needle,repl,1)
elif 'source_mode = "BUILT_ONLY_ENRICHMENT"' not in text: raise SystemExit("Safe-stop: enrich_session body changed")

text = text.replace('        "model": MODEL,\n        "session_date": session_date,\n        "source_provenance": "HISTORICAL_CANDLE_RECONSTRUCTION",\n', '        "model": MODEL,\n        "session_date": session_date,\n        "source_mode": source_mode,\n        "source_provenance": "HISTORICAL_CANDLE_RECONSTRUCTION",\n', 1)
text = text.replace('        "row_count":doc["row_count"],\n        "status_counts":doc["status_counts"],\n', '        "row_count":doc["row_count"],\n        "source_mode":doc["source_mode"],\n        "status_counts":doc["status_counts"],\n', 1)

P.write_text(text, encoding="utf-8")
print("Applied Historical OI Enrichment V1.1 built-only fallback.")
