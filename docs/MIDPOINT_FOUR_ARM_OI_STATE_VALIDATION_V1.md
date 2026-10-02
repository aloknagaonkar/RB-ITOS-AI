# Midpoint Four-Arm OI State Validation V1

This patch makes option positioning explicit without altering the already-frozen
entry classifier.

## OI state definitions

| Premium | OI | State |
|---|---|---|
| up | up | LONG_BUILDUP |
| down | up | SHORT_BUILDUP |
| down | down | LONG_UNWINDING |
| up | down | SHORT_COVERING |

## Strong directional confirmation

### Bearish

```text
CE SHORT_BUILDUP
+
PE LONG_BUILDUP
=
STRONG_BEARISH
```

### Bullish

```text
CE LONG_BUILDUP
+
PE SHORT_BUILDUP
=
STRONG_BULLISH
```

## Secondary support

Bearish:

```text
CE SHORT_BUILDUP + PE SHORT_COVERING
CE LONG_UNWINDING + PE LONG_BUILDUP
```

Bullish:

```text
CE SHORT_COVERING + PE SHORT_BUILDUP
CE LONG_BUILDUP + PE LONG_UNWINDING
```

## Why this is diagnostic first

The four-arm T+3 classifier was frozen before exact option P&L was reviewed.

Changing the entry rule now because the P&L was weak would create research
contamination.

Therefore V1:

- reports CE state;
- reports PE state;
- reports combined support;
- appends OI reason codes;
- summarizes OI support by arm and block;
- DOES NOT change TRADE_NOW / WAIT / CANCEL.

After this report, OI may become a new predeclared V2 hypothesis, which would
need fresh development/frozen validation rather than being silently inserted
into V1.

E/F/G/H remain unused. OOS-H stays pristine.
