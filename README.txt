B FAMILY — V46 CAP20 RESCUE CROSS-BLOCK DIAGNOSTIC

Purpose:
Study the 5 CAP20 rescues across V43/V44/V45 before any more tuning.

It reports:
- each rescue's point delta vs baseline
- whether it later made a new MFE
- which milestones were cut
- total rescue contribution across all three blocks

No rule changes.
No tuning.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_cap20_rescue_diagnostic_v46.py \
  | tee /tmp/b-family-cap20-rescue-diagnostic-v46.txt

Paste the complete output back.
