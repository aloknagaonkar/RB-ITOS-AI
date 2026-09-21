LIVE UPSTOX FIXED-ANCHOR RECOVERY V1

From ~/RB-ITOS-AI after extracting the ZIP to /tmp/live-upstox-anchor-recovery-v1:

cp /tmp/live-upstox-anchor-recovery-v1/backend/market_lab/live_fixed_session_anchor_recovery_v1.py backend/market_lab/
cp /tmp/live-upstox-anchor-recovery-v1/tests/test_live_fixed_session_anchor_recovery_v1.py tests/
cp /tmp/live-upstox-anchor-recovery-v1/scripts/apply_live_fixed_session_anchor_recovery_v1.py scripts/
cp /tmp/live-upstox-anchor-recovery-v1/scripts/verify_live_fixed_session_anchor_recovery_v1.py scripts/
cp /tmp/live-upstox-anchor-recovery-v1/docs/research/LIVE_FIXED_SESSION_ANCHOR_RECOVERY_V1.md docs/research/

python scripts/apply_live_fixed_session_anchor_recovery_v1.py
python -m pytest tests/test_live_fixed_session_anchor_recovery_v1.py -v

set -a
source .env
set +a
python scripts/verify_live_fixed_session_anchor_recovery_v1.py

git diff -- \
  backend/market_lab/live_fixed_session_anchor_recovery_v1.py \
  backend/market_lab/live_shadow_production_wiring_v1.py \
  tests/test_live_fixed_session_anchor_recovery_v1.py \
  scripts/apply_live_fixed_session_anchor_recovery_v1.py \
  scripts/verify_live_fixed_session_anchor_recovery_v1.py \
  docs/research/LIVE_FIXED_SESSION_ANCHOR_RECOVERY_V1.md

Only after tests + verification pass:

git add \
  backend/market_lab/live_fixed_session_anchor_recovery_v1.py \
  backend/market_lab/live_shadow_production_wiring_v1.py \
  tests/test_live_fixed_session_anchor_recovery_v1.py \
  scripts/apply_live_fixed_session_anchor_recovery_v1.py \
  scripts/verify_live_fixed_session_anchor_recovery_v1.py \
  docs/research/LIVE_FIXED_SESSION_ANCHOR_RECOVERY_V1.md

Never use: git add .
