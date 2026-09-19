# Historical Replay Decision Audit V1.1 — TypeScript strict-null fix

Fixes two `string | undefined` assignment errors in `historicalReplay.tsx`.

`ProgressItem.reason`, `detail`, and `status` are optional, while local decision
audit variables are concrete strings. V1.1 adds deterministic string fallbacks
for C2 confirmed and C2 decision paths.

No strategy behavior or audit semantics are changed.
