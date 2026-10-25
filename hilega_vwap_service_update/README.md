# VWAP observation service lifecycle

This package adds an independent VWAP supervisor to existing application scripts.
No trading worker, Sandbox gate, signal, order, cutoff or API-only restart script
is changed. No cron, systemd unit or OS boot hook is installed.

- `scripts/start.sh` starts the observer after the core API/worker start.
- `scripts/restart.sh` already invokes stop/start, so includes this observer.
- `scripts/stop.sh` stops its supervisor and child.
- `scripts/status.sh` includes its process and collected-record status.
- Supervisor restarts exited collectors with a 5–60 second backoff.
- Collector runs `--watch`, selects current IST date, polls every 60 seconds.
- Existing service startup failures warn without aborting core startup.
- PID start time and exact script identity protect against stale PID reuse.
- Exclusive locks prevent duplicate collectors/supervisors.

Install from repository root on the VM:

```bash
python hilega_vwap_service_update/install.py --check
python hilega_vwap_service_update/install.py
bash scripts/start_hilega_vwap_collector.sh
bash scripts/status_hilega_vwap_collector.sh
```

No frontend rebuild or trading worker restart is required. Start only this new
collector now; future normal start/restart commands include it automatically.
The installer checks source hashes and makes backups; no processes are started
by installation. No local project tests or service execution were run.

If an unmanaged `nohup ... collect.py --watch` is already running, startup reports
that condition and refuses duplication. Identify its PID, stop that specific
collector, then start the managed observer. This package never kills unrelated
or unidentified processes. Existing manually running collectors are not adopted.

Logs/state are under `data/live-observation/hilega-vwap-signal-v1`:
`service.json`, `service.log`, `collector.log`, `errors.jsonl`, `report.json`,
`signal-vwap-observations.jsonl`.
RUNNING indicates a process, not verified provider-data health. Status additionally
reports report update time and available/total observation counts. Check collector
errors for token or provider failures; token renewal remains the existing workflow.

After a VM reboot it starts when your existing application startup calls
`scripts/start.sh` or `scripts/restart.sh`. If nothing starts the application on
boot, this patch alone does not create automatic OS boot startup.

VWAP remains diagnostic in audit inspection. Completed 5m futures VWAP is a
typical-price proxy; no new entry/exit filter or strategy activation is introduced.
