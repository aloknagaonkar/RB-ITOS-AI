# Offline native contract-coverage review

Uses current closed warmup successor status, verifies the immutable release via the existing pinned release-only reader (no credentials), locates the exact pinned native contract-preview rules (SHA 660c92...), and evaluates select/quality as pure functions against the existing private REST quote review. No broker requests, synthetic clock replacing live code, order gates, state capture, strategy action or service changes.

Compares native one-lot ATM preview offsets [0] and full [-2,-1,0,1,2] observation keys with the recorded ten-contract diagnostics. Validates metadata through native selection including minimum lot, freeze quantity and tick size. Evaluates the installed preview's quote-quality defaults at the original recorded receive timestamps, not at the current time. This is explicitly retrospective, not fresh market readiness, production permission or policy approval. Native rules are pinned to the reviewed exact hash; changes block the audit. SDK stream v3's lower-strike tie preference is flagged against native higher-strike ties even when the particular recorded basket happens to match. No installed code is changed to resolve that gap by this tool.

Saved private quote bodies are hashed before/after for consistency, but are not independently authenticated or signed by this review. It never certifies ownership, P&L, fees or broker trade timestamp semantics. No complete production contract-admission claim is made.

Detailed source hashes and native quality results are written only into a new private audit; console shows concise counts/reasons. Runtime status runs before/after without holding maintenance locks.

Local checks: syntax/AST and ZIP integrity. No local behavioral tests. This is a read-only inspection, not another behavioral test suite or deployment.
