# V57 — Full historical B+E coordinator/lifecycle replay

This is the full replay phase requested after the 18+18 confirmed-trend cohort screen.

Unlike V56.5, V57 replays the **current live coordinator itself** minute by minute.

It therefore enforces:

- current opening-reference construction
- midpoint break
- boundary break
- V55 B/E/OTHER boundary ownership
- exactly one active reference at a time
- E immediate entry
- B delayed confirmation
- shared B/E +20 proof
- exact +10-minute runner classifier
- RUNNER_STRENGTHENING
- DEGRADED
- degraded target recovery
- CAP20 rescue
- maximum one post-rescue reentry
- structural terminal

Historical scope:

- B1: 2024-08-16 to 2025-02-05
- B2: 2025-02-06 to 2025-07-16
- B3: 2025-07-17 to 2025-12-11
- B4: 2025-12-12 to 2026-09-08

Acceptance guard:

Boundary ownership counts must remain exactly equal to frozen V55 for all four blocks.

Trade accounting:

- CAP20 rescue = first shadow-leg exit
- optional post-rescue reentry = second shadow leg
- structural terminal closes the active non-rescued or reentered leg
- if a lifecycle remains active at session end, V57 records it as open rather than inventing an exit
- reported points are underlying directional points, not option P&L

No live runtime files are modified by this research script.
