#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-$HOME/RB-ITOS-AI}"
cp backend/market_lab/oi_price_regime_transition_audit_v1_1.py "$REPO/backend/market_lab/"
cp tests/test_oi_price_regime_transition_audit_v1_1.py "$REPO/tests/"
mkdir -p "$REPO/docs/research"
cp docs/research/OI_PRICE_REGIME_TRANSITION_AUDIT_V1_1.md "$REPO/docs/research/"
echo "Applied OI_PRICE_REGIME_TRANSITION_AUDIT_V1_1 to $REPO"
