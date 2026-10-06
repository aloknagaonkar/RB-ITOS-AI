HILEGA CURRENT SESSION DATA CHECK

Copy backend/market_lab/hilega_current_session_data_check_cli_v1.py and
tests/test_hilega_current_session_data_check_cli_v1.py into the matching paths
in your project.

With the backend API running, from the project root run:
  PYTHONPATH=backend python -m market_lab.hilega_current_session_data_check_cli_v1

The command checks that the status API reports today's India-time session, a
state record for today, and a completed 5-minute bar dated today. Exit code 0
means both today's state and bar are returned. Exit code 1 means current data
is missing or incomplete. Exit code 2 means the API could not be checked or
does not return the expected status fields.

For a different API address:
  PYTHONPATH=backend python -m market_lab.hilega_current_session_data_check_cli_v1 --url "http://127.0.0.1:8123/api/live-shadow/hilega-directional/status?fast=true"

The check is read-only. It does not start or restart the worker.
