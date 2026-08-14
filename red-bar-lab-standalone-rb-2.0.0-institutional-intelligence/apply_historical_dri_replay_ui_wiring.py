from __future__ import annotations
from pathlib import Path
from datetime import datetime
import shutil

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "red_bar_lab/ui/pages/research_lab.py"
PAYLOAD = ROOT / "payload"

IMPORTS = '''from red_bar_lab.services.historical_dri_replay import detect_historical_dri_events
from red_bar_lab.services.replay_opportunity_accounting import consolidate_replay_rows
'''

SOURCE_CONTROL = '''        replay_sources = st.multiselect(
            "Replay Sources",
            ["RED_BAR", "DRI_EARLY", "DRI_CONFIRMED"],
            default=["RED_BAR", "DRI_EARLY"],
            key="historical_decision_replay_sources",
            help=(
                "RED_BAR runs the existing reference-level replay. "
                "DRI_EARLY detects completed 1-minute directional breaks immediately. "
                "DRI_CONFIRMED is reserved for progressive 5-minute enrichment."
            ),
        )
        st.caption(
            "Rank-1 opportunity accounting is used for headline performance. "
            "All candidate rows remain available in the detailed replay table."
        )
'''

OLD_BUTTON = '''        if st.button("Run Historical Decision Replay", type="primary", disabled=not coverage.replay_ready):
            try:
                replay_service = HistoricalDecisionReplayService(
                    replay_reader,
                    freshness_seconds=180,
                    hard_expiry_seconds=900,
                    minimum_confidence_pct=70.0,
                    stop_loss_pct=15.0,
                    target_pct=25.0,
                    option_chain_sync=cache_option_sync,
                )
                st.session_state["historical_decision_replay_result"] = (
                    replay_service.run_day(instrument_key, replay_date)
                )
            except ValueError as exc:
                st.warning(str(exc))
            except Exception as exc:
                st.exception(exc)
'''

NEW_BUTTON = '''        if st.button(
            "Run Historical Decision Replay",
            type="primary",
            disabled=(not coverage.replay_ready or not replay_sources),
        ):
            try:
                if "RED_BAR" in replay_sources:
                    replay_service = HistoricalDecisionReplayService(
                        replay_reader,
                        freshness_seconds=180,
                        hard_expiry_seconds=900,
                        minimum_confidence_pct=70.0,
                        stop_loss_pct=15.0,
                        target_pct=25.0,
                        option_chain_sync=cache_option_sync,
                    )
                    st.session_state["historical_decision_replay_result"] = (
                        replay_service.run_day(instrument_key, replay_date)
                    )
                else:
                    st.session_state.pop("historical_decision_replay_result", None)

                dri_events = ()
                if {"DRI_EARLY", "DRI_CONFIRMED"} & set(replay_sources):
                    replay_candles = replay_reader.read_day(
                        instrument_key, replay_date, interval_minutes=1
                    )
                    dri_events = detect_historical_dri_events(replay_candles)
                st.session_state["historical_dri_replay_result"] = {
                    "trading_date": replay_date,
                    "sources": tuple(replay_sources),
                    "events": dri_events,
                }
            except ValueError as exc:
                st.warning(str(exc))
            except Exception as exc:
                st.exception(exc)
'''

DRI_RENDER = '''        dri_replay_result = st.session_state.get("historical_dri_replay_result")
        if (
            dri_replay_result is not None
            and dri_replay_result.get("trading_date") == replay_date
        ):
            selected_sources = set(dri_replay_result.get("sources", ()))
            dri_events = tuple(dri_replay_result.get("events", ()))
            if {"DRI_EARLY", "DRI_CONFIRMED"} & selected_sources:
                st.markdown("##### Historical DRI Signal Replay")
                st.caption(
                    "These events are generated candle-by-candle from completed historical "
                    "1-minute candles. They use the historical candle timestamp and never "
                    "read future candles. EARLY events are created immediately; later "
                    "confirmation will enrich the same opportunity in the next wiring stage."
                )
                if dri_events:
                    st.dataframe(
                        [
                            {
                                "Time": event.timestamp,
                                "Event": event.event_id,
                                "Source": event.source,
                                "Stage": event.stage,
                                "Direction": event.direction,
                                "Setup": event.setup_type,
                                "Trigger": event.trigger_level,
                                "Invalidation": event.invalidation_level,
                                "Fresh Until": event.fresh_until,
                            }
                            for event in dri_events
                        ],
                        width="stretch",
                        hide_index=True,
                    )
                    de1, de2, de3 = st.columns(3)
                    de1.metric("DRI Opportunities", len(dri_events))
                    de2.metric(
                        "Bullish",
                        sum(1 for event in dri_events if event.direction == "BULLISH"),
                    )
                    de3.metric(
                        "Bearish",
                        sum(1 for event in dri_events if event.direction == "BEARISH"),
                    )
                else:
                    st.info(
                        "No historical DRI early-break events met the completed-candle "
                        "criteria for this date."
                    )
                if "DRI_CONFIRMED" in selected_sources:
                    st.info(
                        "DRI_CONFIRMED is visible as a replay source, but progressive "
                        "5-minute enrichment is not yet used for Committee execution in "
                        "this increment. It will reinforce the same EARLY opportunity "
                        "rather than create a duplicate trade."
                    )

'''

OPP_SUMMARY = '''            opportunity_summary = consolidate_replay_rows(replay_result.rows)
            st.markdown("##### Rank-1 Opportunity Summary")
            os1, os2, os3, os4, os5, os6 = st.columns(6)
            os1.metric("Opportunities", opportunity_summary.opportunities)
            os2.metric("Candidates Evaluated", opportunity_summary.candidates_evaluated)
            os3.metric("Trades Selected", opportunity_summary.trades_selected)
            os4.metric("Wins", opportunity_summary.winners)
            os5.metric("Losses", opportunity_summary.losers)
            os6.metric(
                "Opportunity Accuracy",
                f"{opportunity_summary.decision_accuracy_pct:.1f}%",
            )
            st.caption(
                "One Rank-1 row represents each signal opportunity. Lower-ranked "
                "contracts remain in the detailed table for diagnostics and are not "
                "counted as separate trades in this summary."
            )
'''

def backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = path.with_name(path.name + f".before_dri_replay_ui_{stamp}")
    shutil.copy2(path, dest)
    return dest

if not TARGET.exists():
    raise SystemExit(f"Target not found: {TARGET}")

text = TARGET.read_text(encoding="utf-8")
backup(TARGET)

if IMPORTS.strip() not in text:
    text = IMPORTS + text

radio_marker = '''        replay_mode = st.radio(
            "Replay Mode",
            ["Full Session", "Fast Validation"],
            horizontal=True,
            key="historical_decision_replay_mode",
        )
'''
if "historical_decision_replay_sources" not in text:
    if radio_marker not in text:
        raise SystemExit("Replay mode marker not found; research_lab.py layout changed.")
    text = text.replace(radio_marker, radio_marker + SOURCE_CONTROL, 1)

if OLD_BUTTON in text:
    text = text.replace(OLD_BUTTON, NEW_BUTTON, 1)
elif "historical_dri_replay_result" not in text:
    raise SystemExit("Historical replay button marker not found; no changes written.")

result_marker = '''        replay_result = st.session_state.get("historical_decision_replay_result")
'''
if "Historical DRI Signal Replay" not in text:
    if result_marker not in text:
        raise SystemExit("Replay result marker not found; no changes written.")
    text = text.replace(result_marker, DRI_RENDER + result_marker, 1)

summary_marker = '''            st.markdown("##### Live-Style Decision Summary")
'''
if "Rank-1 Opportunity Summary" not in text:
    if summary_marker not in text:
        raise SystemExit("Live-style summary marker not found; no changes written.")
    text = text.replace(summary_marker, summary_marker + OPP_SUMMARY, 1)

TARGET.write_text(text, encoding="utf-8")

for source in (PAYLOAD / "red_bar_lab/tests").glob("*.py"):
    destination = ROOT / "red_bar_lab/tests" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)

print("Installed Historical DRI replay UI wiring.")
print("Added replay source controls, DRI event display, and Rank-1 opportunity summary.")
print("Existing Red Bar replay details and engines remain unchanged.")
