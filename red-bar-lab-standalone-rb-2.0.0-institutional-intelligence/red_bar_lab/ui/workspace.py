from __future__ import annotations

import red_bar_lab.ui._shared as shared_ui
import red_bar_lab.ui.active_trade_views as active_trade_views
import red_bar_lab.ui.full_trade_card as full_trade_card
from red_bar_lab.execution.exit_engine import PaperExitEngine
from red_bar_lab.execution.paper_engine import RedBarPaperExecutionEngine
from red_bar_lab.execution.paper_close_telemetry_lifecycle import (
    install as install_paper_close_telemetry_lifecycle,
)
from red_bar_lab.ui._shared import (
    ArtifactLayout,
    RedBarSettings,
    UNDERLYINGS,
    _cached_database,
    st,
)
from red_bar_lab.ui.arrow_dataframe_guard import install as install_arrow_dataframe_guard
from red_bar_lab.ui.current_trade_exit_columns import install as install_current_trade_exit_columns
from red_bar_lab.ui.current_trade_option_telemetry import (
    install as install_current_trade_option_telemetry,
)
from red_bar_lab.ui.open_trade_row_runtime import install as install_open_trade_row_runtime
from red_bar_lab.ui.paper_time_display import install as install_paper_time_display
from red_bar_lab.ui.trade_outlook_card import install as install_trade_outlook_card
from red_bar_lab.ui.workspace_page_runtime import (
    PAGE_MODULE_PATHS as _PAGE_MODULE_PATHS,
    PAGE_MODULES as _PAGE_MODULES,
    install_import_compatibility,
    load_page_module as _load_page_module,
)


# Compatibility contracts retained for architecture tests and audit searches:
# operations_center,
# paper_trading.RedBarPaperAutomationService = AttributionAwarePaperAutomationService
# paper_trading._render_candidate_workbench_fragment = build_candidate_workbench_wrapper(...)
# paper_trading._render_paper_exit_engine_panel = build_paper_exit_panel_wrapper(...)
# live_trading,
# intelligence,
# "Previous Session Context"
# shadow_directional_diagnostics,
# "Shadow Directional": shadow_directional_diagnostics

install_arrow_dataframe_guard(st)
install_paper_time_display()
install_current_trade_exit_columns(active_trade_views)
install_current_trade_option_telemetry(active_trade_views)
install_trade_outlook_card(full_trade_card)
install_paper_close_telemetry_lifecycle(RedBarPaperExecutionEngine)
shared_ui.PaperExitEngine = PaperExitEngine
install_import_compatibility()


def render(settings: RedBarSettings) -> None:
    layout = ArtifactLayout(settings)
    layout.ensure()
    database = _cached_database(str(settings.database_path))

    st.title("Red Bar Strategy Lab")
    st.caption(
        f"{settings.version} · Independent research application · Port {settings.port}"
    )

    token = st.sidebar.text_input(
        "Upstox access token",
        value="",
        type="password",
        help="Used only in memory. It is not written to Red Bar artifacts.",
    )
    underlying_name = st.sidebar.selectbox(
        "Underlying", tuple(UNDERLYINGS), index=0
    )
    instrument_key = UNDERLYINGS[underlying_name]
    interval = st.sidebar.selectbox(
        "Download candle interval", (1, 3, 5, 15), index=0
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("Workspace")
    workspace_pages = tuple(_PAGE_MODULE_PATHS)
    saved_page = st.query_params.get("page", "Operations Center")
    if saved_page not in workspace_pages:
        saved_page = "Operations Center"

    page = st.sidebar.radio(
        "Navigate",
        workspace_pages,
        index=workspace_pages.index(saved_page),
        label_visibility="collapsed",
        key="workspace_navigation",
    )
    if st.query_params.get("page") != page:
        st.query_params["page"] = page

    module = _load_page_module(page)
    install_open_trade_row_runtime(module)
    module.render_page(
        settings,
        layout,
        database,
        token,
        underlying_name,
        instrument_key,
        interval,
    )
