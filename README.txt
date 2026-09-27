B FAMILY — FROZEN POST-PROOF RUNNER FORWARD VALIDATOR V20
============================================================

Frozen on
---------
2026-09-28

Forward start
-------------
2026-09-29

Minimum horizon
---------------
20 distinct trading sessions.

ALL supplied sessions count, including zero-B sessions.

Frozen classifier
-----------------
For a canonical Family-B event:

1. It must reach +20 before structural invalidation.
2. Observe exactly 10 additional minutes.
3. At the +10m boundary:

RUNNER_STRENGTHENING when BOTH:
- net directional progress from +20 > 0
- directional futures-VWAP change > 0

Otherwise:
- NORMAL_B

No exit behavior is attached.

Input
-----
V20 deliberately requires explicit normalized session files so it does not
guess or silently substitute market data.

Repeat --session for one or more days:

DATE|UNDERLYING_CSV|FUTURES_CSV

Underlying CSV must be compatible with the frozen opening midpoint framework.

Futures CSV must contain timestamp plus either:
- diff / vwap_diff / futures_vwap_diff
OR
- close plus session_vwap/vwap.

Example
-------
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_runner_forward_validator_v20.py \
  --session '2026-09-29|data/.../underlying-2026-09-29.csv|data/.../futures-vwap-2026-09-29.csv' \
  | tee /tmp/b-family-runner-forward-v20.txt

The script appends/replaces session records deterministically in:
data/historical-evidence/hilega-pcr-oi-support-research-v1/
b-family-runner-forward-v20/

Do not change the classifier during the first 20 sessions.
Do not attach an exit rule based on interim results.
