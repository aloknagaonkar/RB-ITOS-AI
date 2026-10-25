# Qualified signal clear of EMA10 — offline research

Control: deployed bullish-gap2-full-wma2-2.0.0-wma40-reversal.
Bullish low>completed signal EMA10, or bearish high<EMA10, permits entry at the completed signal boundary only if every normal signal check passes. Equality/touch/cross keeps existing follow-up. Bullish signal gap>=2 and full magnitude>=2 remain; magnitude measured from the candle immediately preceding the qualified signal to immediate entry. If magnitude fails, retain normal follow-up. No bearish magnitude>=2 requirement.
EMA10 is completed-candle close EMA, not intrabar EMA trajectory.
Only new qualifying signal stage is bypassed; existing follow-ups retain their original validation.
Bearish WMA40 and confirmed bullish reversal unchanged. Opposite bullish monitor explicitly uses deployed gate with full follow-up; no immediate reversal on no-touch signal. Bullish normal exits/cutoff/manual safeguards unchanged. No WMA55/60/70 research exits included.
Private offline module source transformation uses strict anchors; no installed source or services modified. Source version mismatch stops. Decisions are hypothetical boundary-close prices, not option fills or executable fill claims.
CLI --date repeatable; --month default2026-10. Full warmup and complete cutoff required. Control validated then cached by code/input/warmup hash. Cache files untrusted outside own local environment.
Outputs summary.md, signal-comparison.md (executed setup union, dashes not direct veto proof), entry-validation.md, full per-session JSON and report.json. Tests and replay not executed locally; run on Ubuntu VM. Require COMPLETE all sessions.
