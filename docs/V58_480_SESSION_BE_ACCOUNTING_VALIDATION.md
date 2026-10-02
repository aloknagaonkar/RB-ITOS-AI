# V58 — 480-session B+E accounting validation

Replays the current B+E coordinator across B1/B2/B3/B4 = 480 sessions and reports the same Family-B-style research outputs: +20/+30/+50/+75/+100 reach, runner separation, CAP20 beneficial/harmful rescue improvement, later-new-MFE after rescue, one re-entry improvement, and baseline vs CAP20-only vs CAP20+re-entry accounting.

Accounting:
- baseline = entry to structural terminal
- CAP20-only = CAP20 rescue closes the first leg and later re-entry is ignored
- full = CAP20 first leg plus one re-entry leg to structural terminal
- rescue improvement = CAP20-only minus baseline
- re-entry improvement = full minus CAP20-only

Open-at-session-end trades remain unresolved. All results are NIFTY underlying directional shadow points, not option P&L. The validator changes no strategy rule and stops if frozen V55 ownership parity fails.
