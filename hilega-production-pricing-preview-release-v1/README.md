# Non-executable pricing-preview release

Prepared from the validated pricing stage. Not deployed.

Adds stored pricing previews and an authenticated read-only endpoint:
`/api/hilega-production/execution-preparation/pricing`.

The outbox request body remains null. Tick-unit approval, executable
pricing policy and real cash reservation remain pending.

Do not copy files into a running checkout manually. Deployment must
recheck target/dependency hashes, verify affected processes are stopped,
back up their actual current files, journal the apply, and support rollback.
This package does not itself contain an apply or rollback command.

No credentials, account evidence or application databases are included.
