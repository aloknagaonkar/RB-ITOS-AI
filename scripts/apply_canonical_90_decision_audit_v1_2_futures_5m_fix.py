from pathlib import Path

P = Path("backend/market_lab/historical_oi_canonical_decision_audit_v1.py")
if not P.exists():
    raise SystemExit("Safe-stop: decision audit module not found")

text = P.read_text(encoding="utf-8")

start = text.find("def load_futures(path):")
end = text.find("\ndef check(", start)
if start < 0 or end < 0:
    raise SystemExit("Safe-stop: load_futures function boundaries not found")

new_func = '''def load_futures(path):
    # Build causal completed 5-minute futures OI states from the existing
    # 1-minute futures/VWAP CSV. Index by bar-end / decision-available time.
    p=Path(path)
    if not p.exists():
        raise FileNotFoundError(p)

    one_min=[]
    with p.open(newline="",encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            d=ts(r,r.get("session_date"))
            if d:
                one_min.append((d,r))
    one_min.sort(key=lambda z:z[0])

    by_session={}
    for d,r in one_min:
        by_session.setdefault(d.date().isoformat(),[]).append((d,r))

    out={}
    for session_date, rows in by_session.items():
        buckets={}
        for d,r in rows:
            minute=(d.minute//5)*5
            bstart=d.replace(minute=minute,second=0,microsecond=0)
            buckets.setdefault(bstart,[]).append((d,r))

        bars=[]
        for bstart, items in sorted(buckets.items()):
            items=sorted(items,key=lambda z:z[0])
            expected=[bstart+timedelta(minutes=i) for i in range(5)]
            actual=[d.replace(second=0,microsecond=0) for d,_ in items]
            if actual != expected:
                continue

            last=items[-1][1]
            close=n(last.get("close"))
            oi=n(last.get("open_interest"))
            if close is None or oi is None:
                continue

            bars.append({
                "bar_start":bstart,
                "available_at":bstart+timedelta(minutes=5),
                "close":close,
                "oi":oi,
                "instrument_key":last.get("instrument_key"),
                "expiry":last.get("expiry"),
                "contract_source":last.get("contract_source"),
            })

        for i,bar in enumerate(bars):
            state="UNAVAILABLE"
            oi_delta=None
            price_delta=None

            if i>0:
                prev=bars[i-1]
                if (
                    bar["bar_start"]-prev["bar_start"]==timedelta(minutes=5)
                    and bar.get("instrument_key")==prev.get("instrument_key")
                ):
                    price_delta=bar["close"]-prev["close"]
                    oi_delta=bar["oi"]-prev["oi"]

                    if price_delta>0 and oi_delta>0:
                        state="LONG_BUILDUP"
                    elif price_delta<0 and oi_delta>0:
                        state="SHORT_BUILDUP"
                    elif price_delta>0 and oi_delta<0:
                        state="SHORT_COVERING"
                    elif price_delta<0 and oi_delta<0:
                        state="LONG_UNWINDING"
                    else:
                        state="NEUTRAL"

            key=bar["available_at"].replace(second=0,microsecond=0).isoformat()
            out[key]={
                "state":state,
                "close":bar["close"],
                "oi":bar["oi"],
                "oi_change_5m":oi_delta,
                "price_change_5m":price_delta,
                "bar_start":bar["bar_start"].isoformat(),
                "available_at":key,
                "instrument_key":bar.get("instrument_key"),
                "expiry":bar.get("expiry"),
                "contract_source":bar.get("contract_source"),
            }

    return out
'''

text = text[:start] + new_func + text[end:]

required = [
    "Build causal completed 5-minute futures OI states",
    '"available_at":bstart+timedelta(minutes=5)',
    'state="SHORT_COVERING"',
    'out[key]={',
]
missing = [x for x in required if x not in text]
if missing:
    raise SystemExit("Safe-stop: post-check failed: " + ", ".join(missing))

P.write_text(text, encoding="utf-8")
print("Patched decision audit futures loader to causal completed 5m OI bars.")
