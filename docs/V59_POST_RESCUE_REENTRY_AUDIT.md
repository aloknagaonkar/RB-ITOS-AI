# V59 — Focused post-rescue re-entry audit

The 480-session V58 accounting strongly reconfirmed CAP20 rescue and the exact
+10-minute runner classifier. The one post-rescue re-entry did not reconfirm:
only a small number of comparable cases existed and their realized second-leg
results were weak.

V59 does not search for a replacement rule. It audits all existing re-entry
cases candle-by-candle using the same V57 parity-proven replay.

The goal is to distinguish:
- a genuinely weak re-entry rule
- a small-sample artifact
- a timing problem where later new MFE exists but occurs before/after the actual
  re-entry window
- open-at-session-end cases that are not comparable

For each case V59 reports entry, rescue, re-entry, structural terminal, first
leg points, second leg points, baseline structural points, rescue improvement,
re-entry MFE, and whether a new MFE occurred after rescue.
