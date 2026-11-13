"""frontend/styles/global_css.py -- chrome-hiding CSS shared by every page."""
from __future__ import annotations

import streamlit as st

GLOBAL_CSS = """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Baloo+2:wght@500;600;700;800&family=Nunito:wght@400;600;700;800&display=swap');
    [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"],
    #MainMenu, footer { display: none !important; }
    header, [data-testid="stHeader"] {
        background: transparent !important; background-color: transparent !important;
        height: 0 !important; min-height: 0 !important; box-shadow: none !important;
    }
    [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stMainBlockContainer"],
    [data-testid="stBottom"], [data-testid="stBottomBlockContainer"], [data-testid="stSidebar"],
    section.main, .main, #root > div:first-child { background: transparent !important; }
    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: rgba(120,140,180,0.45); border-radius: 999px; }
    </style>
    """


def inject_global_css() -> None:
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
