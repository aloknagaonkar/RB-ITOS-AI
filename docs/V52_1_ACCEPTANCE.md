# V52.1 acceptance

The run is valid only when:

- deterministic B1/B2/B3 manifests each contain exactly 100 unique sessions
- manifest date ranges match expected block boundaries
- explicit underlying conflicts = 0
- explicit futures conflicts = 0
- B4 canonical underlying conflicts = 0
- rebuilt B4 framework event set exactly equals canonical framework event set
- 2026-09-28 is excluded
- V51 threshold remains +/-5
- no streak, direction, or exit tuning is introduced
