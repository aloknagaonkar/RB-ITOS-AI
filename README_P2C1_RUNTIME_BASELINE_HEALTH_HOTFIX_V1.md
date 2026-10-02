# P2C.1_RUNTIME_BASELINE_HEALTH_HOTFIX_V1

This hotfix addresses the issues found by the live smoke test:

- distinct `SESSION_BASELINE_UNAVAILABLE`
- authoritative paper-control value in health
- one evaluation per 5-minute checkpoint
- exact-next-checkpoint P2 guard

Important: today's missing 09:20 baseline is not repaired with synthetic data.
The strategy remains blocked safely for today unless a genuine baseline exists.
