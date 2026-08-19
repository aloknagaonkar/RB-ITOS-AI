# DRI / RSI Standalone Retirement Inventory

Branch: `feat/retire-dri-rsi-standalone`

## Decision

Do not physically delete DRI or RSI-related modules yet.

The standalone strategy ownership paths are retired, but several modules still serve one or more of these purposes:

- Red Bar supporting intelligence
- historical replay and audit compatibility
- persisted bundle/schema compatibility
- test fixtures and regression coverage
- retired UI-module references used to prove that old pages stay hidden

Physical deletion is therefore blocked until a separate import graph and migration change removes those dependencies deliberately.

## Active runtime ownership

Only Red Bar remains an active standalone strategy owner.

The following runtime paths are already restricted to Red Bar:

- background architecture orchestration
- paper strategy authority
- independent strategy shadow evaluation
- unified shadow execution routing
- active shadow comparison
- workspace strategy navigation

DRI and RSI compatibility status is preserved as retired/inactive where required.

## Keep: shared Red Bar intelligence

These categories must remain unless a later Red Bar-specific refactor proves they are unused:

- directional regime reference and policy calculations
- EMA, RSI, DMI, ADX, VWAP and regime evidence calculations
- directional context consumed by Red Bar scoring, filtering or attribution
- shared option, market-structure and volatility evidence

A filename containing `directional_regime` or `rsi` is not sufficient evidence that the module is safe to delete. Usage must be evaluated by responsibility, not by name.

## Preserve: compatibility and historical readers

The following categories remain intentionally available but are not active strategy producers:

- DRI and RSI bundle identities and bundle builders
- historical signal readers and replay adapters
- canonical comparison helpers for old records
- persisted status and journal readers
- paper-authority constants and legacy source identifiers
- retired standalone page module paths

These components protect old persisted data, replay files, diagnostics and tests from schema or import breakage.

## Retired: no new standalone production activity

The following behavior must remain disabled:

- standalone DRI signal production
- standalone RSI Reversal signal production
- DRI or RSI paper activation
- DRI or RSI unified-router acceptance
- DRI or RSI active shadow comparison output
- DRI or RSI workspace navigation
- environment-variable reactivation of standalone DRI or RSI

## Candidate files requiring a future dependency proof

The branch tree still contains implementation and compatibility files such as:

- `red_bar_lab/execution/directional_regime_background.py`
- `red_bar_lab/execution/directional_regime_native_signal.py`
- `red_bar_lab/execution/directional_regime_reference.py`
- `red_bar_lab/execution/directional_regime_policy.py`
- `red_bar_lab/execution/dri_opportunity_context.py`
- `red_bar_lab/execution/early_directional_entry.py`
- `red_bar_lab/execution/bundles/directional_regime_bundle_builder.py`
- `red_bar_lab/execution/bundles/rsi_reversal_bundle_builder.py`
- retired DRI and RSI UI page modules
- DRI and RSI engine modules used by historical tests or adapters

None of these files is approved for deletion by this inventory alone.

## Deletion gate

A module can be deleted only when all of the following are true:

1. No active Red Bar path imports it directly or indirectly.
2. No historical replay, persisted record reader or migration depends on it.
3. No compatibility constant, bundle type or deserializer depends on it.
4. No UI registry, diagnostic tool or test imports it.
5. A replacement migration exists for persisted artifacts when required.
6. Targeted tests and the complete `red_bar_lab/tests` suite pass after removal.
7. The deletion is isolated in a reversible commit.

## Current recommendation

Keep the repository in the current compatibility-first state. Do not delete the old modules during this retirement branch. Any physical cleanup should be handled later as a separate dead-code-removal branch, one dependency group at a time.
