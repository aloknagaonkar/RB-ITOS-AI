from __future__ import annotations

# Keep the standalone package importable even when Streamlit launches this
# file by an absolute path or from a different working directory.
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from red_bar_lab.config import RedBarSettings
from red_bar_lab.ui.workspace import render


def main() -> None:
    settings = RedBarSettings.from_env()
    st.set_page_config(
        page_title=settings.app_name,
        page_icon="🟥",
        layout="wide",
    )
    render(settings)


if __name__ == "__main__":
    main()
