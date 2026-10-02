# P3H.1 positioning-cache adapter

Test:

```bash
python -m pytest tests/test_p3h1_positioning_cache_adapter_v1.py -v
```

Quick discovery for a known session:

```bash
python - <<'PY'
from market_lab.historical_positioning_adapter_v1 import choose_positioning_session
s = choose_positioning_session("2026-08-25")
print("source:", s.source_path)
print("date:", s.session_date)
print("expiry:", s.expiry)
print("rows:", len(s.rows))
PY
```
