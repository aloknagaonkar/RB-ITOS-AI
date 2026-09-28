# Midpoint Strategy — M3B.1 Canonical Parity Patch

Canonical corrections applied before live enablement:

- Family-B delayed structure validity uses midpoint.
- Family-B structural terminal uses adverse midpoint close.
- +20 proof uses favorable 1m high/low excursion, not close.
- Exact +10m classifier net progress is endpoint directional close move minus 20.
- Running MFE for DEGRADED uses favorable high/low excursion.
- DEGRADED remains MFE drawdown > 0 plus prior-minute directional VWAP weakening.
- CAP20 is decided on the first eligible rebreak after recovery+10m.
- If that first eligible rebreak is above +20, later CAP20 rescue is forbidden.
- V48 post-rescue re-entry rule remains unchanged.

Safety remains observation-only with execution disabled and quantity None.
