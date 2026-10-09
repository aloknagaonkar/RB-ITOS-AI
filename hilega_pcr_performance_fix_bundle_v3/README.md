PCR performance fix v3 (requires PCR inspection v2)

Keep browser dashboard closed during installation. Run from repository root with virtual environment active:
python hilega_pcr_performance_fix_bundle_v3/install.py && ./scripts/restart.sh
python hilega_pcr_performance_fix_bundle_v3/check.py
./scripts/status_hilega_upstox_sandbox_worker.sh

Then open a single dashboard tab and Ctrl+F5. Compare CPU/disk activity after 60 seconds against the closed-browser baseline. Do not re-arm just to refresh the UI; existing Sandbox arm/session is retained. Restart can interrupt shadow collection briefly; installer sends no broker orders and does not restart itself. Use after the session cutoff if active trade processing must not be interrupted.

Changes:
- Current context queries at most 32 small observation metadata records, loads full JSON for only the selected current observation. Baseline causality lookup is time-window restricted, metadata-only, limited to 160 rows. The existing positioning engine still reads its short baseline candidate window.
- Per-process bounded server cache (128 entries, 15 seconds), identical requests serialized to avoid duplicate expensive computations.
- Shared browser response and in-flight request cache: all active trade legs share current PCR request for the same horizon. Retained contract expiry/key is checked before displaying its bias. No substitution of another contract.
- No PCR or collection-status polling from a hidden tab. Selected audit fetch stays on demand.
- Main Hilega display refresh interval increased from 5 to 15 seconds. This only affects UI refresh, not shadow signal frequency or Sandbox execution frequency.

Preserved: causal decision joins, missing/stale data unavailable, exact-strike bias, PCR formulas, strategy entries/exits, collection enable flag, expiry settings, journal/database data. No indexes, VACUUM, deletion or database rewrite is performed. Existing disk-intensive endpoints outside PCR are not redesigned here; if load stays high, identify process command and collect endpoint timings.

Verification: 50 tests passed. The SQLite test populates 202 observations, confirms one full current observation load, bounded metadata queries and zero database calls on cache hit. TypeScript/Vite build passed. Actual VM resource improvement remains to be verified; this test is not a benchmark against the user's 6 GB database.
