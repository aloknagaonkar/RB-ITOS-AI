# RB-0.7.4.9 Paper Trading Trader Dashboard

RB-0.7.4.9 refines the Paper Trading Command Center into a trader-oriented
decision screen while keeping live broker execution hard-disabled.

## Main changes

### Trader Recommendation card

The top ranked CE/PE candidate is converted into a compact decision card:

- BUY CE / BUY PE
- exact option contract
- rule confidence
- READY / WAIT status
- entry reference
- paper stop
- Target 1
- informational Target 2
- LOW / MEDIUM / HIGH risk band

The entry reference uses the best ask when available, otherwise LTP.

Current paper execution defaults remain:

- stop: 15% below virtual entry
- Target 1: 25% above virtual entry
- EOD exit: 15:25 IST

Target 2 is displayed at +40% only as an informational planning level in this
release. The automatic paper engine does not execute Target 2 yet.

No expected holding-time estimate is fabricated. That field is intentionally
deferred until completed paper trades provide enough evidence.

### 60-second dashboard auto-refresh

Paper Trading now has:

`Auto-refresh trader dashboard every 60 seconds`

When enabled, the browser refreshes the page every 60 seconds.

Candidate ranking is throttled so ordinary Streamlit widget reruns do not
re-hit Upstox continuously. A new ranking is generated when:

- there is no existing ranking
- BULLISH/BEARISH direction changes
- the previous ranking is at least 55 seconds old
- the user manually presses Refresh & Rank Candidates

The background paper monitor remains the faster lifecycle service and continues
to mark/exit open positions at its configured interval (default 5 seconds).

### Recommended Option Candle before entry

The #1 CE/PE candidate now gets its own candle panel even if no paper position
is open yet.

It shows:

- actual selected option close
- VWAP
- EMA9
- EMA21
- volume
- recent momentum percentage
- up to the latest 90 bars on the chart

This makes it possible to validate the contract itself before virtual entry.

### Momentum scoring fix

RB-0.7.4.8 required at least four candle rows before the momentum component
could score.

If an option had only two or three returned candles, Momentum remained zero
even when the option price was rising.

RB-0.7.4.9 now:

- accepts two or more candle rows
- uses up to a five-bar lookback
- falls back to the immediately previous bar when history is short
- stores `momentum_pct`
- stores `candle_count`
- exposes both in the candidate table
- records candle availability in the candidate reason

Current momentum points:

- >= +0.75% : 10
- >= +0.35% : 8
- >= +0.10% : 6
- >= 0.00%  : 4
- >= -0.25% : 2
- below     : 0

A genuine weak/negative option can therefore still score zero; zero is no
longer caused simply by having fewer than four candles.

### Explainability

The existing Why This Option panel remains and the ranked table now adds:

- Momentum %
- Candle Bars

Greeks remain visible but informational:

- Delta
- Gamma
- IV
- Theta
- Vega

They are deliberately not inserted into the rule score yet. That weighting
belongs to the later Options Intelligence / AI fusion release.

### Automatic paper lifecycle

RB-0.7.4.9 retains the background paper lifecycle from earlier releases:

fresh confirmed signal
-> CE/PE ranking
-> virtual entry
-> live marks
-> MFE/MAE
-> stop/target/EOD virtual exit
-> journal

Starting the platform with `start_red_bar_platform.ps1` starts the background
paper monitor when `UPSTOX_ACCESS_TOKEN` is configured.

## Safety

Live execution remains unavailable.

`ZerodhaLiveExecutionProvider.LIVE_EXECUTION_ENABLED = False`

No broker order-placement method is enabled.

## Next planned release

RB-0.8.0 — AI Learning Engine
