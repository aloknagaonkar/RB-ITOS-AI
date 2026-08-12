# RB-0.7.9.3 — Exit Engine Idle Preview

The Paper Exit Engine is now visible even when there is no open CE/PE
paper position.

When idle, the UI shows:

- Initial Premium SL: -15%
- Breakeven: +15% peak
- Trailing Activation: +20% peak
- Trailing Distance: 10% below peak
- Target 1: +25%
- Target 2: +40% informational
- 15:25 EOD exit
- NIFTY Thesis Invalidation
- Opposite Red Bar
- Option Technical Breakdown
- Volume as advisory evidence
- OI/PCR and Greeks as Shadow-only evidence

The idle panel shows Engine=READY, Position=NONE, Action=WAIT.

When a paper position opens, the live Paper Exit Engine workstation replaces
the idle preview automatically.

No exit thresholds or exit authority changed.
