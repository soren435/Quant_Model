"""
Portfolio Analyzer — v2
A professional Streamlit app for ETF portfolio analysis and strategy backtesting.

Run with:  streamlit run app.py
Architecture:
  src/data/        — data ingestion (Yahoo Finance)
  src/analytics/   — return, risk, portfolio, and backtest calculations
  src/visualization/ — Plotly chart builders
  src/ui/          — page rendering functions (one module per tab)
  src/utils/       — formatting and parsing helpers
  src/i18n/        — translation layer (English default, Danish supported)
"""
import os
import sys
from datetime import date

import streamlit as st
import yaml

sys.path.insert(0, os.path.dirname(__file__))

from src.ui.market_overview import render_market_overview
from src.ui.single_asset import render_single_asset
from src.ui.portfolio import render_portfolio
from src.ui.portfolio_builder import render_portfolio_builder
from src.ui.investment_plan import render_investment_plan
from src.ui.backtest import render_backtest
from src.ui.scenario import render_scenario
from src.ui.engine_historical import render_engine_historical
from src.ui.engine_macro import render_engine_macro
from src.ui.engine_hybrid import render_engine_hybrid
from src.ui.engine_investor import render_engine_investor
from src.ui.saxo_connect import render_saxo_connect
from src.utils.formatting import date_to_str, get_period_label
from src.i18n.translations import get_text

# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Portfolio Analyzer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────

def _load_css(path: str) -> None:
    with open(path) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

_load_css(os.path.join(os.path.dirname(__file__), "assets", "style.css"))

# ── Config ─────────────────────────────────────────────────────────────────────

@st.cache_resource
def load_config() -> dict:
    path = os.path.join(os.path.dirname(__file__), "config.yml")
    with open(path) as f:
        return yaml.safe_load(f)

cfg = load_config()
RF = cfg["settings"]["risk_free_rate"]

# ── Language selection (persists in session state) ─────────────────────────────

if "lang" not in st.session_state:
    st.session_state.lang = "en"

# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    # Language selector — shown first so the rest of the sidebar can use lang
    lang_options = {"English": "en", "Dansk": "da"}
    selected_lang_label = st.selectbox(
        "🌐 Language / Sprog",
        options=list(lang_options.keys()),
        index=0 if st.session_state.lang == "en" else 1,
        key="lang_selector",
    )
    st.session_state.lang = lang_options[selected_lang_label]
    lang = st.session_state.lang

    T = lambda key, **kw: get_text(key, lang, **kw)

    st.title(f"📊 {T('sidebar_title')}")
    st.caption(T("sidebar_subtitle"))
    st.divider()

    st.subheader(T("sidebar_date_range"))
    c1, c2 = st.columns(2)
    with c1:
        start_date = st.date_input(
            T("sidebar_from"),
            value=cfg["settings"]["default_start_date"],
            max_value=date.today(),
        )
    with c2:
        end_date = st.date_input(
            T("sidebar_to"),
            value=date.today(),
            max_value=date.today(),
        )

    if start_date >= end_date:
        st.error(T("sidebar_date_error"))
        st.stop()

    start_str = date_to_str(start_date)
    end_str   = date_to_str(end_date)

    st.caption(T("sidebar_period", label=get_period_label(start_str, end_str)))
    st.divider()
    st.caption(T("sidebar_data_source"))
    st.caption(T("sidebar_disclaimer"))

# ── Navigation tabs ────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11, tab12 = st.tabs([
    T("tab_market_overview"),
    T("tab_single_asset"),
    T("tab_portfolio"),
    "🏗️ Portfolio Builder",
    "💰 Investment Plan",
    T("tab_backtest"),
    T("tab_scenario"),
    "📈 Historical Strategies",
    "🌐 Macro Regime",
    "⚗️ Hybrid Allocation",
    "👤 Investor Profile",
    "🔗 Saxo Connect",
])

with tab1:
    render_market_overview(cfg, start_str, end_str, RF, lang=lang)

with tab2:
    render_single_asset(cfg, start_str, end_str, RF, lang=lang)

with tab3:
    render_portfolio(cfg, start_str, end_str, RF, lang=lang)

with tab4:
    render_portfolio_builder(lang=lang)

with tab5:
    render_investment_plan(lang=lang)

with tab6:
    render_backtest(cfg, start_str, end_str, RF, lang=lang)

with tab7:
    render_scenario(cfg, RF, lang=lang)

with tab8:
    render_engine_historical(cfg, start_str, end_str, RF, lang=lang)

with tab9:
    render_engine_macro(cfg, start_str, end_str, RF, lang=lang)

with tab10:
    render_engine_hybrid(cfg, start_str, end_str, RF, lang=lang)

with tab11:
    render_engine_investor(cfg, start_str, end_str, RF, lang=lang)

with tab12:
    render_saxo_connect(lang=lang)
