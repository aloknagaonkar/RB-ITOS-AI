#!/usr/bin/env bash
set -euo pipefail
systemctl --user start hilega-observation-readiness.service
echo "readiness-monitor: supervised start completed"
