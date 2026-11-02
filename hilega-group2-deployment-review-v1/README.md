# Group 2 deployment compatibility review

Run review.py against the existing combined-v2 review folder and its context adoption digest. This is a static, read-only candidate check. It verifies every manifest file, rejects unmanifested files and symlinks, and binds the context and authority review documents to the prior combined result. It does not certify current running services, broker semantics, production authority, or deployment readiness. The earlier tests are not rerun. No candidate code is imported, no database is opened, no network or service commands are used, and no files are changed.

The installed closed recovery config pins the old release. Installing a changed candidate without reviewing that binding would fail recovery verification. This tool does not update that binding or enable the factory. A new exact deployment/recovery plan and disposable rehearsal remain required.

Local validation: syntax and ZIP integrity only. User runs this review on the VM.
