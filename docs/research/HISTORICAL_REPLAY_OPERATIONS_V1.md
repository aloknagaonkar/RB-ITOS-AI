# Historical Replay Operations V1

Workflow: Select date -> Check readiness -> Download missing -> Run replay -> Poll job -> Refresh existing Historical Replay audit UI.

Verified interfaces:
- `historical_replay_data_v1.readiness(session_date)`
- `historical_replay_data_v1.download_missing(session_date)`
- `historical_replay_day_v1_1.run_day(session_date, overwrite=..., progress=...)`

Safety: observation only, no broker orders, no paper orders, one lock per date, background subprocess, isolated replay output.
