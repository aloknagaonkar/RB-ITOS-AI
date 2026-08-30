# Red Bar Lab — Architecture Evaluation

Reviewer position: primary architect
Date: 2026-08-26
Commit reviewed: `9821ef0` (HEAD) with uncommitted working-tree changes
Scope: whole repository (464 non-test modules, 1,880 test functions)

---

## 1. What the system is

An intraday options trading system for Indian index options (NIFTY 50, BANK NIFTY). It
implements one primary strategy ("Red Bar V2") plus a research layer (options PCR,
directional regime / DRI, market-trend evidence), fed by Upstox and Zerodha market data,
persisted to a single SQLite database, and surfaced through a Streamlit UI.

**Runtime topology.** This is not one process. It is a Streamlit app plus roughly seven
long-lived headless worker processes (`execution/*_worker.py`, `*_monitor.py`,
`background_architecture_orchestrator.py`), all reading and writing the same SQLite file at
`artifacts/red_bar/database/red_bar_strategy.db`. The UI refreshes fragments every 5 seconds
(`run_every="5s"`), so the database is under continuous concurrent read pressure during market
hours while workers write.

**Execution posture.** There is no live order-placement path. Everything terminates in paper,
shadow, or canary tiers. This is the single most important safety property of the codebase and
it is deliberate — `execution/providers.py:60` defaults `kill_switch_active=True`, and every
flag in `config.py` defaults `False`. That posture is correct and should be preserved until the
issues in §3 are resolved.

---

## 2. What is genuinely well built

I want to be specific here, because these parts are good and they establish the target the rest
of the codebase should be pulled toward.

**A dependency-free strategy core.** `strategy/red_bar_v2.py` (425 lines) and
`domain/red_bar_v2/` are pure: frozen dataclasses, no I/O, no database, no Streamlit, no
network. `RedBarV2State`, `RedBarV2Reference`, `RedBarV2DirectionDecision`,
`build_red_bar_v2_reference`, `evaluate_initial_direction`, `evaluate_reversal_direction`,
`evaluate_midpoint_upgrade`. This is exactly right. It is testable, reviewable, and
reason-about-able in isolation. Whoever wrote this understood what they were doing.

**Configuration discipline.** `config.py` is a frozen dataclass with bounded coercion
(`_bounded_int`, `_bounded_float`) so a malformed env var clamps to a safe value rather than
propagating garbage. Enum-like settings resolve to an explicit `"INVALID"` sentinel rather than
silently falling back (`_canonical_paper_mode`, `_provider`). All feature flags default off.
Paths are derived properties, not scattered string joins. This is production-grade.

**Secret redaction at the logging boundary.** `logging_config.py` installs a
`SecretRedactionFilter` with a regex covering `access_token`, `authorization`,
`client_secret`, `refresh_token`, `api_secret`. Correct instinct, correctly placed.

**Default-deny safety gating.** Kill switch defaults to active. Canary is bounded by
`max_actions_per_cycle` (1–2), `max_actions_per_day` (1–50), `max_bundle_age_seconds`,
`failure_threshold`. Staleness is treated as a first-class failure condition, not an edge case.

**A large, fast test suite.** 1,880 test functions run in under four minutes. That ratio is
healthy and it means the suite is actually usable as a feedback loop rather than a nightly
ritual.

**The parity harness.** `services/red_bar_v2_parity.py` reconciles the legacy path against the
canonical path field-by-field across `PARITY_FIELDS`. Building this was the right response to
the problem it addresses. See §3.1 for why it is also a symptom.

---

## 3. Structural problems, ranked

### 3.1 — The Red Bar rules are implemented twice, and the live path uses the wrong copy

This is the highest-severity architectural issue in the repository.

There are two independent implementations of the Red Bar V2 decision logic:

1. The pure core — `strategy/red_bar_v2.py` + `domain/red_bar_v2/` + `services/red_bar_v2_canonical/`
2. The organic live path — `ui/strategy_*.py` orchestrated by `execution/headless_strategy_pipeline.py`

`execution/headless_strategy_pipeline.py` (294 lines) imports roughly 30 `red_bar_lab.ui.strategy_*`
modules. Its import count for `strategy.red_bar_v2` is **zero**. The pure core is used by replay,
validation, shadow, and admission modules — the paths that do not trade. The paths that *do*
produce paper/canary decisions go through the UI-resident copy.

The tell is `services/red_bar_v2_parity.py`. A parity harness exists because two
implementations must be proven to agree. That harness is load-bearing infrastructure whose
entire purpose is to compensate for a duplication that should not exist. Parity checks
constrain drift; they do not prevent it, and they only cover the fields enumerated in
`PARITY_FIELDS`.

The duplication also recurs *within* the UI layer. `ui/strategy_setup_detection.py` (621 lines)
and `ui/strategy_red_bar_setup.py` (102 lines) are roughly 85% identical across their first 110
lines, including duplicate private helpers `_latest` and `_option_alignment`.

**Consequence.** Any rule change must be made in two places by two different mechanisms, and a
missed edit produces divergence that only shows up if a parity field happens to cover it. For a
system that will eventually place real orders, this is the defect class that costs money.

**Direction.** The pure core becomes the single source of truth. `headless_strategy_pipeline`
is rewritten to call it. `ui/strategy_*` decision logic is deleted, not refactored — it is
duplicate, and duplicate code should be removed rather than preserved behind an abstraction.
`red_bar_v2_parity.py` then becomes a temporary migration guard with an explicit deletion date,
which is what a parity harness should be.

### 3.2 — The UI package is the application; the layering is inverted

`red_bar_lab/ui/` contains 128 modules. **80 of them (20,091 lines) never import Streamlit.**
That is not a UI package. That is the application core, stored in the presentation directory.

The dependency direction confirms it: `red_bar_lab/execution/` references `red_bar_lab.ui`
**40 times**. Backend workers depend on the UI package. Risk gates and the kill switch live
under `ui/`.

The measurable cost, verified just now: importing `execution/headless_strategy_pipeline`
transitively loads Streamlit and 1,498 modules into a headless worker process. Importing
`execution/background_architecture_orchestrator` does the same and emits
`streamlit.runtime.caching: No runtime found, using MemoryCacheStorageManager` — meaning
`@st.cache_data`-decorated functions are executing inside worker processes against a degraded
fallback cache with no Streamlit runtime present. Worker cache semantics are therefore
different from UI cache semantics, silently.

`ui/_shared.py` compounds this: 2,321 lines, 27 top-level definitions, **zero public names**
(everything underscore-prefixed), imported by 31 modules. A module imported 31 times has a
public contract whether or not its naming admits it. The underscore prefixes actively mislead
readers about what is safe to change.

**Direction.** Move the 80 non-presentational modules out to `services/`, `strategy/`, and
`risk/` by dependency depth — leaves first, so each move is mechanical and independently
testable. Enforce the invariant afterward with an import-linter contract:
`execution` and `services` must not import `ui`. Rename `_shared.py`'s actually-shared
functions to public names as they move.

### 3.3 — 52 tables, no schema versioning, 151 connection sites

There are 52 distinct `CREATE TABLE IF NOT EXISTS` statements and **151 `sqlite3.connect`
call sites** outside tests. There is no migration framework and no schema version table.

Schema evolution is handled by ad-hoc `ALTER TABLE ... ADD COLUMN` loops wrapped in
try/except, at `storage/database.py:915`, `:925`, `:937`, `:949`, `:1335`, `:2345`. Each is a
hand-rolled idempotent migration. They work, but they are unordered, unversioned, and
unauditable: there is no way to ask the database what shape it is in, no way to detect a
partially-migrated file, and no way to roll back.

`storage/database.py` is 4,109 lines with 90 methods in a single `RedBarDatabase` class. It is
a god object.

WAL mode and `busy_timeout` are applied inconsistently across the 151 connection sites. With
seven writer processes and a 5-second UI refresh loop, inconsistent WAL configuration is a
`database is locked` incident waiting for a volatile session.

**Direction.** Introduce a `schema_version` table and a single ordered migration runner.
Funnel all connections through one factory that applies `journal_mode=WAL`,
`busy_timeout`, and `foreign_keys=ON` uniformly — this is a mechanical change and the single
highest-value-per-hour fix in this section. Then split `RedBarDatabase` along table-family
seams into repositories.

### 3.4 — Error handling swallows evidence

**305 `except Exception` handlers** outside tests. 28 of them are followed immediately by a
bare `pass` or `continue` — failure discarded with no record. Only **13 of 464 non-test
modules** reference logging at all.

For a trading system this is the wrong trade. `read_latest_option_participation`
(`services/option_participation_store.py:199`) returns `[]` when the table is missing, which
is correct; but the broader pattern means a data-feed failure, a schema mismatch, and an empty
market are indistinguishable at the UI — all three render as a blank cell.

`configure_logging` returns a per-run logger that callers must thread manually, so most code
paths simply have no logger available. The design makes the correct behaviour inconvenient,
which is why it is not followed.

**Direction.** Module-level `logging.getLogger(__name__)`, configured once at each process
entry point. Every `except Exception` either logs with context or narrows to the specific
exception it actually expects. Distinguish "no data" from "failed to read data" in the return
type — a result object or a distinct sentinel — so the UI can render them differently.

### 3.5 — The repository carries substantial dead weight

- **53 `apply_*.py` installers at the repository root (9,606 lines).** These embed module
  source as triple-quoted string literals (e.g. `QUALITY_SOURCE = """..."""` in
  `apply_historical_dri_quality_controls.py`) and then perform regex surgery on live files
  with `shutil` backups. This is a second, invisible source of truth for the modules they
  write, entirely outside version control's diff view.
- **140 `README_*.md` files at the root.** No reader can determine which is current.
- **100 `.bak` files** committed or littered in the tree.
- **`_v2` / `_v3` / `_v4` page generations** coexisting, with no indication which is live.
- Ad-hoc `check_*.py` / `diagnose_*.py` / `run_*.py` scripts accumulating at the root
  (24 currently untracked).

**Direction.** Delete the `apply_*.py` installers — git is the change mechanism. Consolidate
the 140 READMEs into `docs/` with one entry point. Remove `.bak` files and add the pattern to
`.gitignore`. Delete superseded page generations. Move diagnostic scripts to `scripts/`.

This is a day of work that will materially change how fast anyone can navigate the codebase.

### 3.6 — No CI, no linter, no type checker

`pyproject.toml` is 281 bytes. It pins three runtime dependencies, sets `testpaths` and
`pythonpath`, and stops. There is no linter, no formatter, no type checker, no CI workflow,
no pre-commit hook, and no pinned lockfile.

Type annotation coverage is already around 89% — the codebase has paid most of the cost of
static typing and is collecting none of the benefit.

The test suite has no `conftest.py` and no markers, so unit tests and slow wall-clock
benchmarks run together and cannot be selected apart. Two consequences observed directly
during this review:

- `test_realistic_chain_cpu_benchmark_is_bounded` fails under full-suite load
  (`assert 2268.64 < 500.0`) and passes standalone in 3.64s. It is a flaky wall-clock
  assertion, and it will erode trust in the suite.
- Several tests assert on implementation text via `inspect.getsource(...)` — for example
  `test_trade_evidence_page_consumes_authoritative_persisted_bundle` asserts the literal
  string `"read_latest_market_evidence_bundle("` appears in a function's source. These tests
  fail on refactors that preserve behaviour and pass on refactors that break it. They are
  anti-tests.

**Direction.** Add `ruff` and `mypy` in non-blocking report mode first, then ratchet.
Add a CI workflow running the suite on push. Add `conftest.py` with `slow` and `benchmark`
markers, deselect benchmarks by default, and convert wall-clock assertions to relative
comparisons. Replace `inspect.getsource` assertions with behavioural ones.

### 3.7 — Correctness depends on the host clock being configured for IST

**47 naive `datetime.now()` calls and 47 naive `date.today()` calls** outside tests, against a
domain where session boundaries (09:15, 15:30 IST), expiry selection, and candle bucketing are
all timezone-critical. `zoneinfo` and `Asia/Kolkata` are used in places —
`execution/attribution_automation.py:99` correctly does `datetime.now(IST)` — but the
convention is not enforced.

The system is currently correct only because it runs on a host whose local time is IST. Run it
in a UTC container and expiry selection, session gating, and trading-date derivation all shift.
This is a portability bug today and a correctness bug the day it is deployed anywhere else.

**Direction.** One `clock.py` module exposing `now_ist()` and `trading_date()`. Ban naive
`datetime.now()` / `date.today()` via a lint rule. This also makes time injectable, which
removes a class of test flakiness.

### 3.8 — Runtime monkeypatching of a third-party module

`ui/arrow_dataframe_guard.py:83` reassigns `streamlit.dataframe` at runtime to wrap every call
in `arrow_safe_frame`. It is guarded against double-install and it solves a real Arrow
serialization problem. But it makes `st.dataframe` mean something different inside this
application than its documentation says, discoverable only by finding this file — and it will
break on a Streamlit internals change with a confusing stack trace.

**Direction.** Replace with an explicit `safe_dataframe(...)` helper that call sites use
directly. Enforce with a lint rule banning bare `st.dataframe`. Same protection, no action at
a distance.

---

## 4. Immediate action items

**The working tree is currently red.** `test_market_readiness_workspace.py::test_trade_evidence_page_consumes_authoritative_persisted_bundle`
fails because uncommitted changes removed the `read_latest_market_evidence_bundle(` call the
test asserts on. Full suite: **1,958 passed, 1 failed in 238.73s**. Resolve before committing —
either restore the call or update the test to match the new intent.

`ui/market_trend_research_panel.py` has moved **+580/-28** past `a9c3058` in the working tree.
That is a large uncommitted delta on a file that was just modified; commit it in reviewable
pieces rather than one drop.

The open defects from the `a9c3058` review still stand — in particular the ATM±5 PCR window
vs ATM±4 participation window mismatch, which produces permanently blank cells for the outer
strikes, and the duplicated "CE/PE OI change %" column names carrying different meanings in
adjacent tables.

---

## 5. Sequenced remediation plan

Ordered by risk-reduction per unit of effort. Each phase leaves the system working.

**Phase 0 — stop the bleeding (days)**
1. Green the working tree.
2. Single connection factory applying WAL + `busy_timeout` + `foreign_keys` uniformly.
3. `schema_version` table and ordered migration runner.
4. CI workflow running the existing suite on push. Non-blocking `ruff` + `mypy` reports.
5. `conftest.py` with markers; deselect wall-clock benchmarks by default.

**Phase 1 — repository hygiene (days)**
6. Delete the 53 `apply_*.py` installers, the 100 `.bak` files, and superseded page generations.
7. Consolidate 140 root READMEs into `docs/` behind one entry point.
8. Move root diagnostic scripts to `scripts/`.

**Phase 2 — fix the layering (weeks)**
9. `clock.py`; migrate all 94 naive time calls; lint-ban the naive forms.
10. Module-level loggers at every process entry point; eliminate the 28 silent swallows.
11. Move the 80 non-presentational `ui/` modules out by dependency depth, leaves first.
12. Add an import-linter contract: `execution`/`services` must not import `ui`.
13. Verify no worker process imports Streamlit.

**Phase 3 — collapse the duplication (weeks)**
14. Rewrite `headless_strategy_pipeline` against `strategy/red_bar_v2` + `domain/red_bar_v2`.
15. Run the parity harness continuously through the migration; require zero divergence.
16. Delete the `ui/strategy_*` decision logic and the
    `strategy_setup_detection` / `strategy_red_bar_setup` overlap.
17. Delete `red_bar_v2_parity.py` once one implementation remains.

**Phase 4 — split the god object (weeks)**
18. Decompose `RedBarDatabase` (4,109 lines, 90 methods) into table-family repositories behind
    explicit interfaces.
19. Replace `inspect.getsource` structural tests with behavioural equivalents.

---

## 6. Assessment

The domain modelling here is better than the code organization. There is a clean, well-designed
strategy core, disciplined configuration, real safety gating, and a fast test suite of
meaningful size — the hard conceptual work is done and done well.

What has not happened is the consolidation. The system grew by accretion: new capability was
added next to old capability rather than replacing it, and the artifacts of that growth are
still present — two implementations of the primary strategy, an application living in the UI
directory, 53 source-generating installers, 140 READMEs, 100 `.bak` files. None of these are
conceptual failures. They are deferred cleanup, and the interest is now visible as a parity
harness that exists to compensate for a duplication.

The one thing I would not compromise on: **do not enable a live order path until §3.1 is
resolved.** Two implementations of a trading rule, where the live path uses the copy that is
not the reviewed source of truth, is the specific configuration in which a rule change silently
does the wrong thing with real capital. Everything else on this list is engineering debt that
can be paid down incrementally. That one is a correctness risk.

The current default-deny, no-live-orders posture is the right place to be while this work
happens.
