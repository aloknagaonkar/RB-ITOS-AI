# Red Bar changes

Replace the matching files inside:
`red-bar-lab-standalone-rb-2.0.0-institutional-intelligence/`

Changes:
1. `EXPIRED` and duplicate candidates finalize as `NOT_ELIGIBLE`.
2. The 12:45-13:15 Mid-Session level is published only with all 30 one-minute rows.
3. Subsequent scans retry automatically when delayed data arrives.
4. Regression tests cover both changes.

Run:
`python -m pytest red_bar_lab/tests -q`
