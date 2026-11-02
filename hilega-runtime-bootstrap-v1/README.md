# Closed bootstrap and runtime import closure candidate

Run on the VM only:

    .venv/bin/python hilega-runtime-bootstrap-v1/apply_and_test.py --repo "$PWD"
    .venv/bin/python hilega-runtime-bootstrap-v1/apply_and_test.py --repo "$PWD" --integration

Requires the passing 246-case provisioning report and its unchanged staged manifest.
Eight new tests; combined selection expects 254. No behavioral tests were run in the packaging workspace.

Combines explicit gated bootstrap, read-only existing-adapter preflight, consolidation of transitively imported flat candidate modules, and an AST import inventory. It copies candidate modules into a new stage without executing them. Installed backend dependencies remain inventoried and hash-bound by the existing baseline; this is not a self-contained release or complete distribution lock. Dynamic loaders and external packages remain explicitly reported for review.

RegisteredBootstrap requires explicitly supplied Source, existing Store, journal, approved private-context path/digest and clock. Its constructor reads no private files. The installed gate runs before database/private reads. The bootstrap never constructs Store, provisions secrets, enrolls owners, resumes the controller or registers itself in the running worker. The existing signed-owner loader performs context verification after the gate. Test positive paths intercept transport and use temporary databases.

This package stages an assembly primitive, not production activation. Fresh first-seed enrollment still requires the previously reviewed workflow and a genuinely fresh signed unsent preparation. No stale seed is refreshed or manufactured. Local candidate keys are not a provisioned production trust authority. Broker validation, pricing/partial-fill policies, fees/cash handling, full release regression and a reviewed deployment remain pending.
