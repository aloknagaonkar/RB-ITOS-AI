# Bounded preparation window candidate

Run `.venv/bin/python hilega-group2-bounded-window-v1/manage.py --repo "$PWD"`.

Runs 12 state-machine tests, the pinned V2 review (10 tests and current closed deployment check), and two actual bundled worker rehearsals against new disposable databases: native arm followed by independent deadline pause; initiator SIGKILL followed by independent deadline pause. Each window lasts 12 seconds. No application units are controlled. Worker environment is explicitly constructed without credentials. One synthetic non-signal observation record supplies a current source timestamp; no eligible signal or atomic preparation is manufactured.

Deadline intent is fsynced before a separate watchdog starts; watchdog readiness precedes native resume. Normal failures request native pause. Native adapter requires a disposable marker; no live apply command is provided. Explicit `guard.py --recover` recovers only disposable state.

Limitations: watchdog loss, machine power failure and automatic reboot recovery are NOT validated or configured. A durable state file plus independent process is not a complete production timeout guarantee. Systemd-managed guard/recovery, fresh-signal atomic preparation rehearsal, quiescent backups and exact approved live state plan remain required. The maintenance proposal is not an executable live plan.

No behavioral tests executed locally; syntax checked only. Prior 314-case regression is not rerun. Original runtime/source bundles are not modified.
