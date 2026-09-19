# Historical Replay Equivalent Multi-Config Session V1

A historical session may contain multiple stored config IDs when the collector
configuration changed intraday.

Multiple IDs are merged only when normalized `PCRConfig` values are identical
after excluding two non-replay-semantic fields:

- `name`
- `interval_seconds`

All other fields must match after Pydantic default normalization. This keeps
provider, underlying, expiry, wings, anchor semantics, freshness limits and
trend settings fail-closed.

The snapshot index then loads observations from all equivalent config IDs for
the day, ordered by Observation.id. The latest compatible config ID is used only
as the coordinator's representative config.

If any replay-relevant field differs, replay remains blocked.
