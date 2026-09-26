# Hilega / OI / Red-Midpoint + VWAP Overlay Research v1

This package overlays **Nifty futures VWAP** on the existing Hilega, OI/PCR, true-interval-sequence, and opening-red-midpoint research.

It does not modify Hilega logic and does not enable execution.

## Existing VWAP source

The script uses:

```text
data/historical-evidence/
midpoint-v2-nifty-futures-vwap-v1-all180.csv
```

This dataset already contains:

```text
timestamp
open
high
low
close
volume
session_cumulative_volume
session_vwap
```

## VWAP features

At each Hilega entry or joinable red-break event:

```text
futures close
session VWAP
price - VWAP in points
price - VWAP in %
VWAP 5m slope
VWAP 10m slope
VWAP 15m slope
```

The event is then classified:

```text
ALIGNED_STRONG
ALIGNED_PRICE
NEAR_VWAP
OPPOSED_PRICE
OPPOSED_STRONG
```

Directional interpretation:

```text
Bullish:
  close > VWAP + VWAP rising = ALIGNED_STRONG

Bearish:
  close < VWAP + VWAP falling = ALIGNED_STRONG
```

`NEAR_VWAP` currently means within ±5 futures points. This is descriptive research only, not a frozen threshold.

## Included analyses

- all Hilega trades vs VWAP alignment
- bullish and bearish separately
- 5m OI relation + VWAP
- previous 3–5% intensity / no-13h candidate + VWAP
- true OI interval sequence + VWAP
- opening-red midpoint / low-break outcomes + VWAP where exact event timestamps are joinable

## Run

Copy:

```text
hilega_vwap_overlay_research.py
```

to:

```text
~/RB-ITOS-AI/scripts/
```

Then:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/hilega_vwap_overlay_research.py \
  | tee /tmp/hilega-vwap-overlay.txt
```

## Outputs

```text
data/historical-evidence/
hilega-pcr-oi-support-research-v1/
vwap-overlay-research-v1/
```

Files:

- `hilega-vwap-overlay-trades-v1.csv`
- `opening-red-vwap-overlay-v1.csv` when red-event joins are available
- `vwap-overlay-summary-v1.txt`

Research only. No production filter is frozen by this script.
