V40.1 — EVENT DISCOVERY PATCH
==============================

Why V40 failed:
- raw data was present for all 180 sessions
- V40 searched only CSV filenames containing "b-event"/"b-events"
- canonical B-family artifacts use different filenames
- result: discovered_b_event_keys=0

V40.1 fixes only discovery:
- scans CSV schema rather than filename
- supports entry/date/direction aliases
- deduplicates event rows
- prints top source files

V38_CAP50 logic is unchanged and frozen.
No tuning is added.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_v38_cap50_validation_v40_1.py \
  | tee /tmp/b-family-v38-cap50-validation-v40_1.txt

Paste the complete output, including TOP EVENT SOURCES.
