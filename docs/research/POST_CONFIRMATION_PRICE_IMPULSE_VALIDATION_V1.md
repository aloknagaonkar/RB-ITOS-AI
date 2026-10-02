# POST_CONFIRMATION_PRICE_IMPULSE_VALIDATION_V1

## Why this study exists

The 46-session holdout validated the structural layer:

- opposite ALL_3 survives to candle 2
- candle-2 futures OI aligns with the target direction

That structure strongly predicted **continued ALL_3 persistence**.

However, it did not by itself produce strong post-confirmation NIFTY continuation.
This study therefore keeps the structural gate frozen and asks a separate question:

> At candle 2, is there already causal evidence of price impulse that separates events with
> better subsequent NIFTY movement?

## Cohort discipline

Use the **54-session development cohort only**.

The 46-session holdout has already been inspected and must not be used to invent or tune
the price-impulse features in V1.

## Frozen structural gate

An event enters this study only when:

1. a new opposite-direction ALL_3 run appears,
2. it survives to candle 2,
3. candle-2 futures OI direction supports the new ALL_3 direction.

## Causal features available at candle 2

No fitted cutoffs are used.

- target-signed spot move candle1 -> candle2
- target-signed futures-price move candle1 -> candle2
- target-signed VWAP distance at candle 2
- change in target-signed VWAP distance candle1 -> candle2
- spot + futures-price impulse agreement

Natural sign boundary only:

- positive = supportive
- zero/negative = non-supportive

## Evaluation-only outcomes

From candle 2:

- signed NIFTY spot move +5m
- +10m
- +15m
- +30m
- positive-direction rate at each horizon
- MFE/MAE over next 15m and 30m

This is not option-premium PnL and creates no entry rule.

## Decision after V1

If one or more causal impulse features show stable separation in development:

1. freeze the definition,
2. do not tune it on the already-viewed 46-session holdout,
3. validate on an untouched older cohort, e.g. OOS-E/F/G/H as appropriate,
4. only then consider integration into the option-entry architecture.
