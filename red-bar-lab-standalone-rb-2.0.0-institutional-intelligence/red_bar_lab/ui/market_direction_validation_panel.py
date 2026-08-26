from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Callable, Mapping, TypeVar

from red_bar_lab.services.market_direction_validation import (
    DirectionComponent,
    build_market_direction_validation,
)
from red_bar_lab.services.market_evidence_bundle_store import (
    read_latest_market_evidence_bundle,
)
from red_bar_lab.services.market_trend_research.repository import (
    MarketTrendResearchRepository,
)
from red_bar_lab.services.nifty_futures_snapshot_store import (
    read_nifty_futures_snapshots,
)
from red_bar_lab.services.option_participation_store import (
    read_latest_option_participation,
)
from red_bar_lab.ui._shared import _arrow_safe_rows, st
from red_bar_lab.ui.market_trend_research_panel import (
    MARKET_TREND_RESEARCH_UI_REFRESH_SECONDS,
)


F = TypeVar("F", bound=Callable[..., object])
_SOURCE_LIMITS_SECONDS = {
    "NIFTY structure": 390.0,
    "Options": 120.0,
    "Futures": 390.0,
    "PCR": 30.0,
}


def _fragment(run_every: str) -> Callable[[F], F]:
    fragment = getattr(st, "fragment", None)
    if callable(fragment):
        return fragment(run_every=run_every)
    return lambda function: function


def _aware_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(
                text[:-1] + "+00:00" if text.endswith("Z") else text
            )
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _source_rows(
    *,
    bundle: Mapping[str, object],
    option_rows: list[dict[str, object]],
    futures: Mapping[str, object],
    projection: Mapping[str, object],
    now: datetime,
) -> list[dict[str, object]]:
    sources = (
        ("NIFTY structure", bundle.get("underlying_timestamp")),
        ("Options", option_rows[0].get("observed_at") if option_rows else None),
        ("Futures", futures.get("bar_close_timestamp") or futures.get("latest_timestamp")),
        ("PCR", projection.get("source_timestamp")),
    )
    result: list[dict[str, object]] = []
    for name, raw_timestamp in sources:
        timestamp = _aware_timestamp(raw_timestamp)
        age = (
            max(0.0, (now - timestamp.astimezone(timezone.utc)).total_seconds())
            if timestamp is not None
            else None
        )
        limit = _SOURCE_LIMITS_SECONDS[name]
        status = "MISSING" if age is None else "STALE" if age > limit else "FRESH"
        result.append(
            {
                "Source": name,
                "Source timestamp": raw_timestamp or "Not available",
                "Age": "Not available" if age is None else f"{age:.1f}s",
                "Freshness limit": f"{limit:.0f}s",
                "Status": status,
            }
        )
    return result


def _score(value: float, maximum: float) -> str:
    return f"{value:.1f}/{maximum:.0f}"


def _component_rows(components: tuple[DirectionComponent, ...]) -> list[dict[str, object]]:
    return [
        {
            "Component": item.name,
            "Conclusion": item.conclusion,
            "Bullish score": _score(item.bullish_score, item.maximum_score),
            "Bearish score": _score(item.bearish_score, item.maximum_score),
            "Quality": item.quality,
        }
        for item in components
    ]


def _render_component(component: DirectionComponent) -> None:
    label = (
        f"{component.name} — {component.conclusion} · "
        f"Bull {_score(component.bullish_score, component.maximum_score)} · "
        f"Bear {_score(component.bearish_score, component.maximum_score)}"
    )
    with st.expander(label, expanded=False):
        st.caption(
            f"Quality: {component.quality} · Maximum contribution: "
            f"{component.maximum_score:.0f} · Authority: OBSERVATIONAL_ONLY"
        )
        if component.details:
            st.dataframe(
                _arrow_safe_rows(list(component.details)),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("No persisted evidence is available for this component.")


def _render_validation_cycle(
    database_path: str | Path,
    *,
    underlying: str,
    now: datetime | None = None,
) -> None:
    """Read each persisted source once and render one lightweight cycle."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    bundle = read_latest_market_evidence_bundle(
        database_path,
        underlying_name=underlying,
    )
    option_rows = read_latest_option_participation(
        database_path,
        underlying_name=underlying,
    )
    futures_rows = read_nifty_futures_snapshots(
        database_path,
        underlying_name=underlying,
        limit=1,
    )
    projection = MarketTrendResearchRepository(database_path).latest_projection(
        underlying=underlying
    )
    result = build_market_direction_validation(
        authoritative_bundle=bundle,
        option_rows=option_rows,
        futures_snapshot=futures_rows[0] if futures_rows else None,
        pcr_projection=projection,
    )
    source_rows = _source_rows(
        bundle=bundle or {},
        option_rows=option_rows,
        futures=futures_rows[0] if futures_rows else {},
        projection=projection or {},
        now=current.astimezone(timezone.utc),
    )
    unavailable_sources = tuple(
        str(row["Source"])
        for row in source_rows
        if row["Status"] != "FRESH"
    )
    stale = bool(unavailable_sources)
    displayed_conclusion = "WAIT" if stale else result.conclusion
    displayed_quality = "STALE" if stale else result.quality
    st.dataframe(
        _arrow_safe_rows(
            [
                {
                    "Research conclusion": displayed_conclusion,
                    "Bullish score": f"{result.bullish_score:.1f}/100",
                    "Bearish score": f"{result.bearish_score:.1f}/100",
                    "Score separation": f"{result.score_gap:.1f}",
                    "Quality": displayed_quality,
                    "Authority": result.authority,
                }
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    if stale:
        st.warning(
            "WAIT: mandatory evidence is missing or stale: "
            + ", ".join(unavailable_sources)
            + ". Scores remain visible for diagnosis and have no trading authority."
        )
    if stale:
        st.info(
            "The diagnostic score is not promoted to a current market "
            "conclusion until every mandatory source is fresh."
        )
    elif result.conclusion == "BULLISH":
        st.success(result.reason)
    elif result.conclusion == "BEARISH":
        st.error(result.reason)
    elif result.conclusion in {"SIDEWAYS", "CONFLICT"}:
        st.warning(result.reason)
    else:
        st.info(result.reason)

    st.markdown("#### Component summary")
    st.dataframe(
        _arrow_safe_rows(_component_rows(result.components)),
        width="stretch",
        hide_index=True,
    )
    for component in result.components:
        _render_component(component)

    with st.expander("Source freshness and alignment", expanded=False):
        st.dataframe(
            _arrow_safe_rows(source_rows),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            f"This fragment refreshes every "
            f"{MARKET_TREND_RESEARCH_UI_REFRESH_SECONDS:g} seconds and performs "
            "persisted reads only."
        )

    with st.expander("Decision policy and architecture boundary", expanded=False):
        st.write(
            {
                "winning_score_required": 65,
                "score_separation_required": 15,
                "structure_must_agree": True,
                "options_or_futures_must_agree": True,
                "signal_generated": False,
                "canonical_bundle_created": False,
                "opportunity_queued": False,
                "paper_trade_created": False,
                "authority": result.authority,
            }
        )


@_fragment(run_every=f"{MARKET_TREND_RESEARCH_UI_REFRESH_SECONDS:g}s")
def _market_direction_validation_fragment(
    database_path: str | Path,
    underlying: str,
) -> None:
    try:
        _render_validation_cycle(database_path, underlying=underlying)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        st.warning(
            "Market Direction Validation could not refresh from persisted "
            f"evidence ({type(exc).__name__}). The next isolated refresh will retry."
        )


def render_market_direction_validation_panel(
    database_path: str | Path,
    *,
    underlying: str,
) -> None:
    """Render a timed, read-only validation over persisted evidence."""

    st.markdown("### Market Direction Validation")
    st.caption(
        "Read-only composite research over persisted NIFTY structure, option "
        "buildup/VWAP, futures and PCR evidence. It does not generate signals, "
        "bundles, opportunities or trades."
    )
    _market_direction_validation_fragment(database_path, underlying)


__all__ = ["render_market_direction_validation_panel"]
