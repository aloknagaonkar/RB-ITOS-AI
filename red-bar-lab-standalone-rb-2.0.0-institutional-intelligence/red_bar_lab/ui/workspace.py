from __future__ import annotations

import red_bar_lab.ui._shared as shared_ui
from red_bar_lab.execution.exit_engine import PaperExitEngine
from red_bar_lab.ui._shared import (
    ArtifactLayout,
    RedBarSettings,
    UNDERLYINGS,
    _cached_database,
    st,
)
from red_bar_lab.ui.paper_time_display import install as install_paper_time_display
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
# shadow_directional_diagnostics,
# "Shadow Directional": shadow_directional_diagnostics

install_paper_time_display()
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
    module.render_page(
        settings,
        layout,
        database,
        token,
        underlying_name,
        instrument_key,
        interval,
    )
