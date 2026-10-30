from __future__ import annotations
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path("data/historical-evidence/historical-oi-build")
MODEL = "HISTORICAL_OI_BUILT_SOURCE_ADAPTER_V1_3"
RESEARCH_WINGS = 5
HORIZONS = (5, 10, 15)


def _load(session_date: str) -> dict[str, Any]:
    p = ROOT / session_date / "positioning.json"
    if not p.exists():
        raise KeyError(f"No built historical OI data for {session_date}")
    payload = json.loads(p.read_text(encoding="utf-8"))
    sessions = payload.get("sessions") or []
    if len(sessions) != 1:
        raise ValueError(f"Expected one built session for {session_date}")
    s = sessions[0]
    if s.get("status") != "AVAILABLE":
        raise ValueError(f"Built session {session_date} is not AVAILABLE")
    return s


def _num(v):
    if v in (None, ""): return None
    try: return float(v)
    except (TypeError, ValueError): return None


def _sum(rows, key):
    vals = [_num(r.get(key)) for r in rows]
    if not vals or any(v is None for v in vals): return None
    return float(sum(vals))


def _pct(delta, previous):
    return None if delta is None or previous in (None, 0) else delta / previous * 100.0


def _pcr(pe, ce):
    return None if pe is None or ce in (None, 0) else pe / ce


def _basket(all_rows, center, strike_interval, wings=RESEARCH_WINGS):
    required = {float(center) + offset * float(strike_interval) for offset in range(-wings, wings + 1)}
    index = {float(r["strike"]): r for r in all_rows}
    return [index[s] for s in sorted(required) if s in index]


def _pattern(ce, pe):
    mapping = {
        ("SHORT_BUILDUP", "LONG_BUILDUP"): "BEARISH_CE_SB_PLUS_PE_LB",
        ("LONG_BUILDUP", "SHORT_BUILDUP"): "BULLISH_CE_LB_PLUS_PE_SB",
        ("SHORT_COVERING", "LONG_UNWINDING"): "BULLISH_CE_SC_PLUS_PE_LU",
        ("LONG_UNWINDING", "SHORT_COVERING"): "BEARISH_CE_LU_PLUS_PE_SC",
    }
    return mapping.get((ce, pe), f"ATM_{ce or 'UNAVAILABLE'}__{pe or 'UNAVAILABLE'}")


def built_inventory():
    rows = []
    if ROOT.exists():
        for child in sorted(ROOT.iterdir(), reverse=True):
            if not child.is_dir(): continue
            sp, dp = child / "build-status.json", child / "positioning.json"
            if not sp.exists() or not dp.exists(): continue
            try: status = json.loads(sp.read_text())
            except Exception: continue
            if status.get("status") != "COMPLETE": continue
            try: s = _load(child.name)
            except Exception: continue
            rows.append({
                "session_date": child.name,
                "expiry": s.get("expiry"),
                "rows": 74,
                "raw_positioning_rows": s.get("row_count"),
                "raw_sidecar_wings": s.get("wings"),
                "source": "BUILT",
            })
    return {"model": MODEL, "source": "BUILT", "session_count": len(rows), "sessions": rows}


def build_checkpoint_rows(session_date: str):
    s = _load(session_date)
    raw = s.get("rows") or []
    by_ts = defaultdict(list)
    for r in raw:
        by_ts[datetime.fromisoformat(str(r["timestamp"]))].append(r)
    if not by_ts: raise ValueError("No positioning rows")

    first = min(by_ts)
    start = first.replace(hour=9, minute=20, second=0, microsecond=0)
    end = start.replace(hour=15, minute=25)
    strike_interval = float(s.get("strike_interval") or 50.0)

    morning = by_ts.get(start, [])
    if not morning:
        raise ValueError("09:20 rows missing.")
    fixed_atm = _num(morning[0].get("moving_atm"))
    fixed_base = _basket(morning, fixed_atm, strike_interval)
    if len(fixed_base) != 11:
        raise ValueError("09:20 fixed basket incomplete.")

    fixed_strikes = [float(r["strike"]) for r in fixed_base]
    fixed_ce_base = _sum(fixed_base, "ce_open_interest")
    fixed_pe_base = _sum(fixed_base, "pe_open_interest")
    fixed_pcr_base = _pcr(fixed_pe_base, fixed_ce_base)

    checkpoints = []
    t = start
    while t <= end:
        checkpoints.append(t)
        t += timedelta(minutes=5)

    out = []
    for ts in checkpoints:
        all_current = by_ts.get(ts, [])
        if not all_current: continue

        spot = _num(all_current[0].get("spot"))
        moving_atm = _num(all_current[0].get("moving_atm"))
        moving = _basket(all_current, moving_atm, strike_interval)
        if len(moving) != 11: continue

        ce = _sum(moving, "ce_open_interest")
        pe = _sum(moving, "pe_open_interest")
        current_pcr = _pcr(pe, ce)
        moving_strikes = [float(r["strike"]) for r in moving]

        horizons = {}
        for minutes in HORIZONS:
            prev_index = {float(r["strike"]): r for r in by_ts.get(ts - timedelta(minutes=minutes), [])}
            previous = [prev_index[x] for x in moving_strikes if x in prev_index]
            prev_ce = _sum(previous, "ce_open_interest") if len(previous) == 11 else None
            prev_pe = _sum(previous, "pe_open_interest") if len(previous) == 11 else None
            ce_delta = ce - prev_ce if ce is not None and prev_ce is not None else None
            pe_delta = pe - prev_pe if pe is not None and prev_pe is not None else None
            prior_pcr = _pcr(prev_pe, prev_ce)
            horizons[str(minutes)] = {
                "minutes": minutes,
                "ce_previous_same_strikes": prev_ce,
                "pe_previous_same_strikes": prev_pe,
                "ce_delta": ce_delta,
                "pe_delta": pe_delta,
                "ce_pct": _pct(ce_delta, prev_ce),
                "pe_pct": _pct(pe_delta, prev_pe),
                "imbalance": pe_delta - ce_delta if ce_delta is not None and pe_delta is not None else None,
                "prior_pcr": prior_pcr,
                "current_pcr": current_pcr,
                "pcr_change": current_pcr - prior_pcr if current_pcr is not None and prior_pcr is not None else None,
            }

        h5 = horizons["5"]
        atm_row = min(moving, key=lambda r: abs(float(r["strike"]) - float(moving_atm)))
        ce_state, pe_state = atm_row.get("ce_5m_state"), atm_row.get("pe_5m_state")

        fixed_index = {float(r["strike"]): r for r in all_current}
        fixed = [fixed_index[x] for x in fixed_strikes if x in fixed_index]
        fixed_complete = len(fixed) == 11

        fce = _sum(fixed, "ce_open_interest") if fixed_complete else None
        fpe = _sum(fixed, "pe_open_interest") if fixed_complete else None
        fce_delta = fce - fixed_ce_base if fce is not None and fixed_ce_base is not None else None
        fpe_delta = fpe - fixed_pe_base if fpe is not None and fixed_pe_base is not None else None
        fpcr = _pcr(fpe, fce)

        def fwd(minutes):
            later = by_ts.get(ts + timedelta(minutes=minutes), [])
            if not later or spot is None: return None
            later_spot = _num(later[0].get("spot"))
            return None if later_spot is None else later_spot - spot

        out.append({
            "block": "BUILT", "source": "BUILT", "session_date": session_date,
            "timestamp": ts.isoformat(), "time": ts.strftime("%H:%M"),
            "spot": spot, "moving_atm": moving_atm, "fixed_atm": fixed_atm,
            "m_ce_oi": ce, "m_pe_oi": pe,
            "m_ce_delta": h5["ce_delta"], "m_pe_delta": h5["pe_delta"],
            "m_ce_pct": h5["ce_pct"], "m_pe_pct": h5["pe_pct"],
            "m_activity": abs(h5["ce_delta"]) + abs(h5["pe_delta"]) if h5["ce_delta"] is not None and h5["pe_delta"] is not None else None,
            "m_pcr_previous": h5["prior_pcr"], "m_pcr": current_pcr, "m_pcr_change": h5["pcr_change"],
            "m_common_strikes": str(moving_strikes), "moving_horizons": horizons,
            "atm_ce_price_pct": _num(atm_row.get("ce_5m_premium_change_pct")),
            "atm_pe_price_pct": _num(atm_row.get("pe_5m_premium_change_pct")),
            "ce_state": ce_state, "pe_state": pe_state,
            "fixed_strikes": str(fixed_strikes), "fixed_complete": fixed_complete,
            "fixed_ce_oi_baseline_0920": fixed_ce_base, "fixed_pe_oi_baseline_0920": fixed_pe_base,
            "fixed_ce_oi": fce, "fixed_pe_oi": fpe,
            "f_ce_delta": fce_delta, "f_pe_delta": fpe_delta,
            "f_ce_pct": _pct(fce_delta, fixed_ce_base), "f_pe_pct": _pct(fpe_delta, fixed_pe_base),
            "f_activity": abs(fce_delta) + abs(fpe_delta) if fce_delta is not None and fpe_delta is not None else None,
            "f_imbalance": fpe_delta - fce_delta if fce_delta is not None and fpe_delta is not None else None,
            "f_pcr_baseline": fixed_pcr_base, "f_pcr": fpcr,
            "f_pcr_change": fpcr - fixed_pcr_base if fpcr is not None and fixed_pcr_base is not None else None,
            "forward_5m_points": fwd(5), "forward_10m_points": fwd(10), "forward_15m_points": fwd(15),
            "pattern_family": _pattern(ce_state, pe_state),
        })

    return {
        "model": MODEL, "source": "BUILT", "session_date": session_date,
        "expiry": s.get("expiry"), "row_count": len(out),
        "raw_positioning_rows": s.get("row_count"), "raw_sidecar_wings": s.get("wings"),
        "fixed_atm": fixed_atm, "fixed_strikes": fixed_strikes, "rows": out,
    }
