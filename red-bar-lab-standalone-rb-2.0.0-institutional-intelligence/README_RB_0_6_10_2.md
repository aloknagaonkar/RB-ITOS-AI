# RB-0.6.10.2 Database Lifecycle Hotfix

Fixes:

`AttributeError: 'RedBarDatabase' object has no attribute 'update_signal_state'`

Root cause:
`update_signal_state()` existed in `database.py`, but it was accidentally
defined at module level instead of inside the `RedBarDatabase` class.

Fix:
- move `update_signal_state()` inside `RedBarDatabase`;
- add a regression test that creates a signal, changes it to CLOSED, and reads
  the persisted state back.

No strategy, entry, exit, benchmark, or market-data logic is changed.
