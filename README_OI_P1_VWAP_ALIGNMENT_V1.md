# OI P1 + VWAP Alignment V1

This is the exact study requested: when CE/PE OI transition P1 fires, what was
the **causally available** futures VWAP state?

Important timing:

If OI P1 is stamped `14:25`, the `14:25` 5m futures candle is not closed until
`14:30`. Therefore the causal VWAP candle at the instant of P1 is normally the
`14:20` candle, available at `14:25`.

The table prints BOTH:
- `VWbar`: latest fully completed VWAP candle usable at P1.
- `SameLbl`: candle carrying the same 14:25 chart label, for visual validation
  only. Its close cannot be used for a 14:25 decision.

## Run

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest tests/test_oi_p1_vwap_alignment_v1.py -v

python -m market_lab.oi_p1_vwap_alignment_v1 \
  --transitions data/historical-evidence/oi-transition-outcome-analysis-v1.json \
  --vwap-profile data/historical-evidence/vwap-trend-day-profile-v1.json \
  --trend-days-only \
  --output data/historical-evidence/oi-p1-vwap-alignment-v1.json \
  --csv-output data/historical-evidence/oi-p1-vwap-alignment-v1.csv

python -m market_lab.oi_p1_vwap_alignment_report_v1 \
  --input data/historical-evidence/oi-p1-vwap-alignment-v1.json
```

Chart-check Aug 25:

```bash
python -m market_lab.oi_p1_vwap_alignment_report_v1 \
  --input data/historical-evidence/oi-p1-vwap-alignment-v1.json \
  --date 2026-08-25
```

Chart-check Sep 8:

```bash
python -m market_lab.oi_p1_vwap_alignment_report_v1 \
  --input data/historical-evidence/oi-p1-vwap-alignment-v1.json \
  --date 2026-09-08
```

This is descriptive research only. It does not change V1 or authorize trading.
