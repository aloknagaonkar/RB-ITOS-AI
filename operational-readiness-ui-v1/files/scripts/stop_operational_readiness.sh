#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [ -f data/operational-readiness.pid ]; then
    PID="$(cat data/operational-readiness.pid)"
    if kill -0 "$PID" 2>/dev/null && [[ "$(tr '\0' ' ' < "/proc/$PID/cmdline")" == *market_lab.operational_readiness_v1* ]]; then kill "$PID"; fi
    rm -f data/operational-readiness.pid
fi
