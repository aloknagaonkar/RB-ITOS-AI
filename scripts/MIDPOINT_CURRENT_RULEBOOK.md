# Midpoint Strategy Current Rulebook

This document records the implemented observation-only Midpoint entry and exit
rules. It separates live-enabled behavior from research-only or disabled paths.

## Safety

- `observation_only=true`
- `execution_enabled=false`
- `paper_order_enabled=false`
- `quantity=None`
- `order_sent=false`

## Current live gates

| Family or feature | Live shadow |
|---|---:|
| B | Enabled |
| E | Enabled |
| Repeated B/E rearm | Enabled |
| C | Disabled; replaced by repeated B/E revalidation |
| D | Disabled |
| PM_E | Disabled; isolated validation only |
| NORMAL_B_PROVED three-tier candidate | Enabled, observation only |
| DEGRADED_EXIT candidate | Enabled, observation only |
| Exact NORMAL_B classifier-close exit | Disabled; research only |
| Post-rescue re-entry | Disabled |

## Opening references

The 09:15-09:19 candle is ignored. From 09:20 onward the coordinator retains
the first completed RED five-minute structure and the first completed GREEN
five-minute structure.

| Reference | Direction | Midpoint break | Boundary break | Terminal |
|---|---|---|---|---|
| RED | Bearish | 1m close below midpoint | 1m close below low | 1m close above midpoint |
| GREEN | Bullish | 1m close above midpoint | 1m close above high | 1m close below midpoint |

Both midpoint and boundary evidence use completed one-minute closes.

## Canonical B/E boundary ownership

At a confirmed boundary break:

1. If full Candidate A already exists, ownership is `OTHER_FRESH_A`; no B or E
   entry is permitted.
2. Otherwise, if directional Futures-minus-VWAP strength is greater than +5,
   ownership is E.
3. Otherwise, ownership is B and the delayed confirmation watch starts.

Full Candidate A requires:

- Bearish: raw Futures-minus-VWAP is below -5 now, and at least one observation
  in the current-minus-five-minute through current window was at or above -5.
- Bullish: raw Futures-minus-VWAP is above +5 now, and at least one observation
  in that window was at or below +5.

### Family E entry

E enters immediately at the completed boundary-break candle close when:

- the midpoint close break occurred;
- the original boundary close break occurred;
- Candidate A was not already full at the boundary; and
- directional Futures-minus-VWAP strength is greater than +5.

### Family B entry

B starts a maximum ten-minute delayed watch at the boundary break. It enters on
the completed confirmation candle only when:

- the directional structure remains valid;
- price remains beyond the original boundary; and
- full Candidate A appears within ten minutes.

The watch expires after ten minutes or invalidates when the directional
structure is lost.

## Repeated B/E rearm

Every entered B/E generation may arm exactly one next generation.

1. During the active generation, NIFTY must touch the original midpoint
   intrabar.
2. The origin generation must structurally close.
3. A later candle must freshly close beyond the original boundary. The previous
   close must not already be beyond that boundary.
4. The canonical boundary owner is recalculated:
   - E: immediate `E_REARM_ENTRY`;
   - B: delayed B watch and `B_REARM_ENTRY` only after confirmation;
   - `OTHER_FRESH_A`: reject.
5. Same-candle terminal and re-entry is prohibited, and only one Midpoint trade
   may be active.

The original reference midpoint and boundary remain authoritative for all
generations.

## PM_E afternoon false-break reversal

PM_E uses the exact 30 completed one-minute candles from 12:45 through 13:14.
It locks the PM high, low and midpoint.

Required sequence:

1. First completed close outside one PM boundary.
2. Completed close back through the PM midpoint in the opposite direction.
3. A later fresh completed close beyond the opposite PM boundary.
4. Canonical boundary ownership must be E.

| First break | Midpoint recross | Opposite break | Candidate |
|---|---|---|---|
| Close above PM high | Close below midpoint | Fresh close below PM low | Bearish PM_E |
| Close below PM low | Close above midpoint | Fresh close above PM high | Bullish PM_E |

An intrabar midpoint touch does not satisfy the PM_E recross. The opposite
boundary break must occur later than the recross, same-candle reversal entry is
blocked, and the PM structure is single-use.

PM_E is presently disabled in live shadow.

## Shared proof and classifier

The management lifecycle is shared by qualified entries.

1. `PLUS20_PROOF` occurs on the first completed one-minute bar whose favorable
   intrabar high/low excursion reaches at least +20 underlying points. The
   event's close-based directional-points field can therefore be below +20.
2. Classification occurs at the exact proof timestamp plus ten minutes.
3. `RUNNER_STRENGTHENING` requires both:
   - net completed-close progress from +20 is positive; and
   - directional Futures-VWAP change from proof is positive.
4. If either condition fails, classification is `NORMAL_B`.
5. A missing exact classifier minute is recorded as unavailable rather than
   substituted with a future candle.

## RUNNER_STRENGTHENING management

The observation route is `DEGRADED_EXIT_CANDIDATE`.

`DEGRADED_STARTED` fires on the first completed candle after classification
where:

- giveback from the running favorable excursion to the current close is
  positive; and
- the prior-minute directional Futures-VWAP change is negative.

The candidate values its underlying exit at the completed trigger-candle close
and its five-contract option exit at the next exact option-minute open. It does
not re-enter and does not close the authoritative baseline lifecycle.

## NORMAL_B management: three-tier candidate

The classifier candle establishes `NORMAL_B_PROVED`; candidate exit evaluation
starts on later candles.

| Zone | Condition | Protection |
|---|---|---|
| Tier 1 | MFE <= +30 | No floor; structural midpoint backstop |
| Tier 2 | MFE > +30 | Static +15 close-profit floor |
| Tier 3 | MFE > +45 | Ratchet = max(previous floor, highest Tier-3 close profit - 10) |

Additional rules:

- A later intrabar +50 target touch assumes an exact +50 research fill.
- Floor exit requires a completed close strictly below the active floor and is
  valued at the actual close, not the theoretical floor.
- After 30 minutes without a new MFE, exit is scheduled at the next exact
  completed-minute close.
- Structural midpoint invalidation remains the backstop.
- Candidate re-entry is prohibited.

The proposed immediate dual-failure classifier-close exit remains disabled.

## Unproved and legacy structural management

Trades that never prove +20 retain midpoint invalidation as their exit. This is
the principal loss cohort currently scheduled for initial-risk IS/OOS research.

For the authoritative runner lifecycle, the legacy recovery/CAP20 evidence
continues in parallel:

- recovery requires a completed close strictly above the degraded target;
- after at least ten minutes, the first rebreak below that target is evaluated;
- CAP20 rescue occurs only when directional points are at or below +20;
- post-rescue re-entry is disabled.

## Observation-only option valuation

The exact five-contract tape currently covers B/E origin and B/E rearm entries:

- bullish entry observes CE;
- bearish entry observes PE;
- contracts are ATM-2 through ATM+2;
- entry valuation is the next exact option-minute open;
- candidate exit valuation is the next exact option-minute open;
- missing exact minutes remain unavailable and are never forward-filled.

PM_E option-tape inclusion must be validated separately before PM_E is enabled.
