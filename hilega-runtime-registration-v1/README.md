# Dependency review and proposed registration

Run on the VM only:

    .venv/bin/python hilega-runtime-registration-v1/apply_and_test.py --repo "$PWD" --integration

Integration first reruns the preceding 254-case bootstrap suite and bounded running-health check, then executes six new tests. The report therefore expects 260 cases across two sequential pytest runs. Without --integration, six new tests run after the bounded health check, requiring an existing passing 254-case report.

No package install, controller resume, secret provisioning, owner enrollment, service command or installed-source edit is performed. Registration is a proposed contract, with no apply action.

The dynamic review verifies the reviewed evidence loader, collector module, dependencies.json and every pinned fixed target. It executes none of them. This establishes the fixed file pin chain, not the full transitive imports or safety of arbitrary future dynamic loaders.

python-dotenv's expected version is 1.2.3. Its observed version and installed Python-source hashes are recorded without importing dotenv or opening environment files. A version difference is reported for review and does not trigger installation. Passing tests do not certify dependency reconciliation. The snapshot is not a wheel artifact hash lock.

The current runtime remains closed. A real deployment still requires reviewed runtime assembly and supervisor approval, trusted production authority, broker evidence validation, policy/fee/cash decisions, full regression, closed rollout and approved fresh-seed enrollment. No stale or synthetic seed is substituted for a real signal.
