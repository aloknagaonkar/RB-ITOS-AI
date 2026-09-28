B FAMILY — V25 RUNNER EXIT DIAGNOSTIC
=======================================

Purpose
-------
Study the 11 frozen RUNNER_STRENGTHENING events from V24 before defining any
runner exit rule.

V25 measures:
- time from classification to +50/+75/+100
- max pullback before each milestone
- directional futures-VWAP context
- peak favorable excursion after classification
- giveback from peak to canonical structural invalidation
- classification-to-invalidation duration

It does NOT:
- define an exit
- tune a stop
- tune a trailing threshold
- change Family B
- change V20 classifier
- touch production/runtime/order code

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_runner_exit_diagnostic_v25.py \
  | tee /tmp/b-family-runner-exit-diagnostic-v25.txt

Paste the complete output back.
