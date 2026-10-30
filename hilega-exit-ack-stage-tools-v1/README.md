# Durable exit acknowledgement stage v1

Fixture-only development stage. It does not install runtime code or enable live exits.

## VM validation
    .venv/bin/python -m zipfile -e hilega-exit-ack-stage-v1.zip hilega-exit-ack-stage-tools-v1
    .venv/bin/python -W error::ResourceWarning -m unittest discover -s hilega-exit-ack-stage-tools-v1 -p 'test_*.py' -v
    .venv/bin/python -W error::ResourceWarning hilega-exit-ack-stage-tools-v1/validate_exit_ack_fixture.py

Expected: 130 tests pass and EXIT_ACK_REFERENCE_FIXTURE_PASS.
The tests and demonstration create temporary synthetic databases, use the supplied
adapter's FixtureTransport to generate fake acknowledgements, then remove the
temporary data. They never read .env, the real account pin or production databases,
and never send broker orders or make network calls.

## Added behavior
bind_fixture_ack writes an exit acknowledgement reference and its audit event
atomically in the separate staged reference ledger. It reads the fixture adapter
through an attached database transaction and leaves it unchanged.
Only FIXTURE: scope, STAGED_REFERENCE_ONLY reference metadata and OFFLINE_FIXTURE
adapter metadata are accepted.

The existing receipt checker validates request fingerprints, disabled draft,
fixed place endpoint, exactly one place attempt, wire match, durable receipt
provenance, exact integer HTTP 200, a single valid acknowledged order ID and
unique order binding. The new stage also validates the atomic exit binding,
signed exit reference, parent request and acknowledged parent order references,
SELL contract/quantity and same-session reference time.

Successful binding records ACKNOWLEDGED_NOT_FILLED_REFERENCE_ONLY.
It never manufactures trade fills or marks exposure flat. It grants neither
ownership nor reservation release. Identical replay is idempotent and changed
references conflict. An injected failure after the acknowledgement insert or
before commit rolls back the staged reference and audit event.

The binder does not invoke transport, create an attempt, retry an unknown outcome,
or adopt an order merely because the instrument or tag matches. Its tests use a
fake transport before calling the binder; fake placement is explicitly fixture
evidence, not a real order. A timeout after fake acceptance without a durable
receipt remains unresolved and is not resubmitted.

## Limits and next work
This extends the previous isolated stages (115 tests) with 15 acknowledgement
tests. It is still not application integration. No live account orders can be
adopted by this API. Production source/adapter paths remain untouched.
Do not remove the fixture guards or relabel live evidence to bypass them.

Receipt evidence is historical local provenance, not a broker-issued signature
or fresh position proof. Cross-session reconciliation, chronological SELL-fill
attribution, fees/P&L, terminal flatness, full lifecycle ownership, production
risk limits/daily-stop, real cash reservation and release remain pending.
The staged ledger has no release API. Existing pending exit references remain
retained after acknowledgement.

130 local tests passed with ResourceWarning treated as an error. VM validation
is pending. Runtime integration and production execution remain false.
