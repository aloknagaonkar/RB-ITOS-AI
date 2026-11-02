# Combined Group 2 managed recovery and preparation validation

Run `.venv/bin/python hilega-group2-managed-recovery-v2/manage.py --repo "$PWD"`.

Requires the prior bounded V2 PASS receipt. Runs the pinned current read-only review (10 cases), six synthetic signed-evidence preparation tests and six managed-recovery contract tests. Tests use the deployed bundle's backend/runtime and fixture files copied from reviewed repository commit bcfcab663b8cd46c43bbde173d77b8988f8ac177. No production gate is patched.

Two new disposable native-worker/systemd guard rehearsals: normal deadline and SIGKILL of the guard's main process, with ExecStopPost native pause recovery. Only uniquely named hilega-disposable-window-*.service transient user units are started/killed/stopped. No application service is controlled. Persisted-state recovery is repeated explicitly after guard exit; actual VM reboot is NOT tested and no boot recovery units are installed.

Synthetic fresh signals are tested in process through Source with temporary attached application/adapter databases, not through the managed worker process. Assertions cover atomic binding, signed cash reference, replay, hard-gate transport closure, stale signal, and precommit rollback. Non-signal observation fixtures are used for the actual managed worker windows. Live apply remains unavailable.

Remaining work: boot recovery installation/ordering and full manager loss; managed-window eligible-signal end-to-end test; exact live state/backup/approval plan. Draft maintenance proposal is not executable. No live authority, enrollment, broker credential access, funds injection or live controller changes.

Behavioral tests are VM-only; locally only syntax/archive checks are performed.

V2 supplies validated owned /run/user/UID runtime and Unix session-bus socket settings to systemd-run/systemctl in the stripped disposable child environment. It retains MANAGED-LAUNCH.json stderr/stdout and records the unique disposable unit before launch. No application environment file is edited.
