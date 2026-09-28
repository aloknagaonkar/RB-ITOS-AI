# V58.1 FIX3

Inspection of the actual V58 file showed the earlier patches targeted the wrong
function signature.

Current V58 uses:

`def replay(day,u,fut):`

and:

`load_module(...)`

FIX3 patches that exact function and delegates replay to the already
parity-proven V57 `replay_session(day,u,fut)`.

Only replay-source duplication is removed. V58 accounting remains unchanged.
