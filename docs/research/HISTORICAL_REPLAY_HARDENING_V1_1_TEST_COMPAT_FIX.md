# Historical Replay Hardening V1.1 — Test Compatibility Fix

The existing operations API test replaces `subprocess.Popen` with a minimal
`Dummy` object that does not define `.pid`.

Production `subprocess.Popen` objects do provide `.pid`, but the new hardening
code accessed `process.pid` unconditionally, which broke the pre-existing test.

This patch changes only:

`process.pid`

to:

`getattr(process, "pid", None)`

Production behavior is unchanged; real jobs still record the launcher PID.
The test double now records `launcher_pid: null`.
