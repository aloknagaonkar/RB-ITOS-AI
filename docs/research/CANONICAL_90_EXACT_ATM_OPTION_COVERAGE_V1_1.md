# Canonical 90 Exact ATM Option Coverage Gate V1.1

The real 370-signal diagnostic found two mechanical issues.

1. Shared-contract overwrite bug

Multiple eligible events can reuse the same exact option instrument during the
same session. V1 stored one expected timestamp set per `(session, instrument)`
and overwrote earlier event windows with the last event's window. This falsely
created `MISSING_ENTRY_MINUTE` results even though the exact wanted minute was
present. The diagnostic showed exact offset 0 was available in all 97 cases.

V1.1 reads the union of required source timestamps per contract and then checks
each event against its own exact entry-to-+15m window.

2. Session-end censoring

The 8 incomplete paths are late-session entries whose missing timestamps start
at 15:30 or later. V1.1 classifies these as `SESSION_END_CENSORED` instead of
generic missing data.

No nearest-strike fallback.
No nearest-time fallback.
No strategy rule change.
No P&L logic added.
