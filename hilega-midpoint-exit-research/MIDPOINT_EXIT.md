# Post-entry midpoint exit variant

Three policies: deployed5m; unchanged BODY50_1M_WAIT; BODY50_1M_MIDPOINT_EXIT.
Only trades actually opened by BODY50_1M_BREAKOUT get the new protection.
Bullish exits on a completed1m close strictly below original5m signal midpoint;
bearish strictly above. Equality holds. No wick triggering, no moving reference,
no protection on entry candle, no guaranteed fill at midpoint. Execution mark is
the completed1m close. Existing-route positions retain their old exits.

Protection is checked from the minute after entry, including coincident5m
boundaries before normal5m evaluation.14:55cutoff retains originalopen mark and
priority. A protection exit clears pending followups/watch and bullish reversal
monitor; normal5m setup processing continues. Same-boundary existing confirmed
entry may occur only through normal strategy processing, not midpoint permission.

Other5m exits and confirmed reversal remain; earliest applicable exit wins.
After an early exit all subsequent signals/positions are replayed, not filtered
from old trades. No live changes or orders. No project tests/replays run locally.

Run test_rules.py, test_batch.py and test_midpoint.py on VM. Existing tests cover
pure rules/reporting; they do not prove all integration state transitions.
Review Aug5 first with batch.py --date2026-08-05 (space after option) and then
the full saved Aug/Sep/Oct inputs. --session-input is optional for batch.py.

summary.md contains three-policy totals and daily midpoint impact;
midpoint-exit-trades.md includes every protected-variant execution and reason.
Daily JSON policies.BODY50_1M_MIDPOINT_EXIT.audit records every active midpoint
check and exit, plus unchanged5m evaluations. Costs excluded; live unchanged.
