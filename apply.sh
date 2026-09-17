#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-$HOME/RB-ITOS-AI}"
cp backend/market_lab/atm_plus_minus_5_trade_path_analysis_v1.py "$REPO/backend/market_lab/"
cp tests/test_atm_plus_minus_5_trade_path_analysis_v1.py "$REPO/tests/"
mkdir -p "$REPO/docs/research"
cp docs/research/ATM_PLUS_MINUS_5_TRADE_PATH_ANALYSIS_V1.md "$REPO/docs/research/"
echo "Applied ATM_PLUS_MINUS_5_TRADE_PATH_ANALYSIS_V1 to $REPO"
