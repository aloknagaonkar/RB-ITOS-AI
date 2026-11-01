# Repeat retirement checks v1

Adds five fixture tests: expiry before commit, stale capture, retirement tampering,
closeout tampering, and live-scope rejection before database access.

This package does not implement third-entry admission or change any runtime source.
It uses the candidate files and fixture dependencies already present on your VM.
The earlier combined suite was reported as 62 passed. This package's tests have
not been run here: run the complete regression on your VM. Expect 67 cases if
the baseline files still contain the reported 62 cases.

From the RB-ITOS-AI checkout, extract this ZIP into a new directory, then run:

```bash
.venv/bin/python hilega-repeat-retirement-checks-v1/apply_and_test.py --repo "$PWD"
```

The runner verifies the packaged test checksum, refuses to overwrite differing
files, and creates only `$HOME/test_fixture_repeat_retirement_hardening.py`.
It then runs the seven existing suites plus the new tests with the interpreter
you selected. Fixtures write temporary test databases. Runtime sources, production
databases and services are not changed by the installer. Existing Python test
modules execute during pytest collection, as in the previous VM runs.

If tests fail, paste the traceback. Do not enable production execution.
To remove the added tests, delete only the added hardening test file and this
extracted package directory. Existing checkpoint files remain unchanged.
