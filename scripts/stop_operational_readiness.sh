#!/usr/bin/env bash
set -euo pipefail
systemctl --user stop hilega-observation-readiness.service
echo "readiness-monitor: supervised stop completed"
