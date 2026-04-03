"""
Portfolio Builder — guided advisor page.

Structure:
  1. Description
  2. Educational fact box (metric definitions + realistic ranges)
  3. Preference sliders (Return target, Volatility tolerance, Drawdown tolerance)
  4. Dynamic hints based on slider values
  5. Recommended portfolios (top 3) with per-dimension scores
  6. Score transparency explanation
  7. Disclaimer
"""
from __future__ import annotations

import streamlit as st

from src.ui.components.fact_box import render_fact_box

# ── Candidate portfolio presets ────────────────────────────────────────────────
# Characteristics are approximate long-run historical values.
# return_pct / vol_pct use annualized %; max_dd_pct is negative (peak-to-trough).

_PRESETS: list[dict] = [
    {
        "name": "Ultra Conservative — 100% Bonds",
        "tickers": "IEF",
        "weights": "1.0",
        "return_pct":  2.5,
        "vol_pct":     6.5,
        "max_dd_pct": -8.0,
        "description": (
            "Fully invested in intermediate-term US government bonds. "
            "Minimal equity exposure — prioritises capital preservation over growth."
        ),
    },
    {
        "name": "Conservative — 20 / 80 (SPY / IEF)",
        "tickers": "SPY, IEF",
        "weights": "0.2, 0.8",
        "return_pct":  4.0,
        "vol_pct":     7.5,
        "max_dd_pct": -12.0,
        "description": (
            "Mostly bonds with a small equity allocation for modest upside. "
            "Suitable for investors with a short horizon or low risk tolerance."
        ),
    },
    {
        "name": "Moderate — 40 / 60 (SPY / IEF)",
        "tickers": "SPY, IEF",
        "weights": "0.4, 0.6",
        "return_pct":  6.0,
        "vol_pct":    10.5,
        "max_dd_pct": -20.0,
        "description": (
            "Balanced allocation tilted toward capital preservation. "
            "Aims for steady growth while limiting downside exposure."
        ),
    },
    {
        "name": "Balanced 60/40 — Classic",
        "tickers": "SPY, IEF",
        "weights": "0.6, 0.4",
        "return_pct":  7.5,
        "vol_pct":    13.0,
        "max_dd_pct": -28.0,
        "description": (
            "The classic institutional allocation. Broad equity exposure tempered by "
            "a bond buffer — widely used as a balanced long-term benchmark."
        ),
    },
    {
        "name": "Growth — 80 / 20 (SPY / IEF)",
        "tickers": "SPY, IEF",
        "weights": "0.8, 0.2",
        "return_pct":  9.5,
        "vol_pct":    16.0,
        "max_dd_pct": -38.0,
        "description": (
            "Equity-dominated with a small bond buffer to dampen extreme volatility. "
            "Targets long-run capital appreciation with meaningful drawdown risk."
        ),
    },
    {
        "name": "Aggressive — 100% Equities (SPY)",
        "tickers": "SPY",
        "weights": "1.0",
        "return_pct": 10.5,
        "vol_pct":    18.0,
        "max_dd_pct": -51.0,
        "description": (
            "Full US broad-market equity exposure. Maximum long-run growth potential "
            "with the highest drawdown risk — requires a long investment horizon."
        ),
    },
    {
        "name": "Tech Growth — 70% QQQ / 30% IEF",
        "tickers": "QQQ, IEF",
        "weights": "0.7, 0.3",
        "return_pct": 13.5,
        "vol_pct":    20.0,
        "max_dd_pct": -42.0,
        "description": (
            "Heavy allocation to large-cap US tech with a partial bond hedge. "
            "High growth potential, elevated volatility, and significant drawdown risk."
        ),
    },
]

# ── Preference → target range mappings ────────────────────────────────────────

# Maps slider value (1–5) to (min, max) acceptable range for each metric.
_RETURN_TARGETS: dict[int, tuple[float, float]] = {
    1: (1.0,  4.0),
    2: (3.5,  6.5),
    3: (5.5,  9.0),
    4: (8.0, 12.0),
    5: (11.0, 20.0),
}
_VOL_TARGETS: dict[int, tuple[float, float]] = {
    1: (3.0,  9.0),
    2: (8.0, 12.0),
    3: (11.0, 16.0),
    4: (15.0, 21.0),
    5: (19.0, 35.0),
}
_DD_TARGETS: dict[int, tuple[float, float]] = {
    1: (0.0,  10.0),
    2: (8.0,  20.0),
    3: (18.0, 32.0),
    4: (28.0, 45.0),
    5: (38.0, 60.0),
}


def _score_metric(value: float, target: tuple[float, float], penalty: float = 1.2) -> float:
    """
    Score a single metric against a target range (0–10).
    Full marks (10) if value is within range; decreases linearly outside it.
    """
    lo, hi = target
    v = abs(value)
    if lo <= v <= hi:
        return 10.0
    gap = (lo - v) if v < lo else (v - hi)
    return max(0.0, round(10.0 - gap * penalty, 2))


def _score_preset(
    preset: dict,
    return_pref: int,
    vol_pref: int,
    dd_pref: int,
) -> dict[str, float]:
    """
    Compute per-dimension and overall match scores for one preset.
    Returns dict with keys: return_score, vol_score, dd_score, total.
    """
    ret_score = _score_metric(preset["return_pct"],       _RETURN_TARGETS[return_pref])
    vol_score = _score_metric(preset["vol_pct"],          _VOL_TARGETS[vol_pref])
    dd_score  = _score_metric(abs(preset["max_dd_pct"]),  _DD_TARGETS[dd_pref])
    total     = (ret_score + vol_score + dd_score) / 3

    return {
        "return_score": ret_score,
        "vol_score":    vol_score,
        "dd_score":     dd_score,
        "total":        round(total, 2),
    }


def _dynamic_hints(return_pref: int, vol_pref: int, dd_pref: int) -> None:
    """Render context-sensitive guidance boxes based on the current slider values."""

    # Conflict: high return desire but low risk tolerance
    if return_pref >= 4 and vol_pref <= 2:
        st.warning(
            "⚠️ **Conflicting preferences detected.** "
            "A high return target combined with low volatility tolerance is difficult to achieve "
            "in practice. Higher returns historically require accepting higher short-term fluctuations. "
            "Consider raising your volatility tolerance or lowering the return target."
        )
    elif return_pref >= 4 and dd_pref <= 2:
        st.warning(
            "⚠️ **Trade-off alert.** "
            "A high return target with a very low drawdown tolerance is uncommon — "
            "periods of strong equity growth are typically accompanied by deeper drawdowns. "
            "Consider adjusting one of these preferences."
        )

    hints: list[str] = []

    if return_pref == 5:
        hints.append(
            "📈 **High return target (score 5):** Implies significant equity exposure. "
            "Historically, portfolios targeting 12–15 %+ annual returns experience volatility "
            "of 20 %+ and drawdowns exceeding 40 % during market stress."
        )
    elif return_pref == 1:
        hints.append(
            "📈 **Low return target (score 1):** Capital preservation focus. "
            "Realistic in a bond-heavy portfolio, but returns may not keep pace with inflation "
            "over long horizons."
        )

    if vol_pref == 1:
        hints.append(
            "〰️ **Low volatility tolerance (score 1):** "
            "Targeting annualized volatility below 9 % typically requires a large bond allocation "
            "that will significantly reduce expected returns."
        )
    elif vol_pref == 5:
        hints.append(
            "〰️ **High volatility tolerance (score 5):** "
            "Comfortable with swings of 20 %+ annually. This suits aggressive growth strategies "
            "but requires a long investment horizon to recover from drawdowns."
        )

    if dd_pref == 1:
        hints.append(
            "📉 **Very low drawdown tolerance (score 1):** "
            "Limiting maximum loss to −10 % significantly constrains the equity allocation "
            "and growth potential of the portfolio."
        )
    elif dd_pref == 5:
        hints.append(
            "📉 **High drawdown tolerance (score 5):** "
            "Willing to accept losses of 40 %+. This is appropriate for long-term investors "
            "who can hold through full market cycles without panic-selling."
        )

    for hint in hints:
        st.info(hint)


def _render_score_bar(score: float, label: str) -> None:
    """Render a labelled progress bar for a single dimension score (0–10)."""
    col_label, col_bar = st.columns([1, 3])
    with col_label:
        st.markdown(f"**{label}**")
    with col_bar:
        st.progress(int(score * 10), text=f"{score:.1f} / 10")


def _render_recommendation(
    rank: int,
    preset: dict,
    scores: dict[str, float],
) -> None:
    """Render a single ranked portfolio recommendation card."""
    match_pct = int(scores["total"] * 10)
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")

    with st.container(border=True):
        header_col, badge_col = st.columns([4, 1])
        with header_col:
            st.markdown(f"### {medal} {preset['name']}")
        with badge_col:
            st.metric("Overall Match", f"{match_pct} %")

        st.markdown(f"_{preset['description']}_")
        st.markdown(f"**Tickers / Weights:** `{preset['tickers']}` — `{preset['weights']}`")

        st.markdown("**Score breakdown:**")
        _render_score_bar(scores["return_score"], "Return")
        _render_score_bar(scores["vol_score"],    "Volatility")
        _render_score_bar(scores["dd_score"],     "Drawdown")

        st.caption(
            "This portfolio matches your preferences by balancing return and risk "
            f"based on approximate long-run historical data. "
            f"Expected return ≈ **{preset['return_pct']:.1f} %**, "
            f"volatility ≈ **{preset['vol_pct']:.1f} %**, "
            f"max drawdown ≈ **{preset['max_dd_pct']:.0f} %**."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Page entry point
# ═══════════════════════════════════════════════════════════════════════════════

def render_portfolio_builder(lang: str = "en") -> None:
    """
    Render the Portfolio Builder guided advisor page.

    Args:
        lang: UI language code (reserved for future localization). Defaults to "en".
    """
    st.header("🏗️ Portfolio Builder")
    st.caption(
        "Answer three simple questions about your return expectations and risk tolerance. "
        "The builder will recommend portfolios that match your preferences and explain why."
    )

    # ── 1. Educational fact box ────────────────────────────────────────────────
    render_fact_box()

    st.divider()

    # ── 2. Preference sliders ──────────────────────────────────────────────────
    st.subheader("Your Preferences")
    st.markdown(
        "Use the sliders below to describe what you want from your portfolio. "
        "Score **1** = lowest, **5** = highest."
    )

    col_r, col_v, col_d = st.columns(3)

    with col_r:
        st.markdown("**📈 Return Target**")
        st.caption("How much annual growth are you aiming for?")
        return_pref = st.slider(
            "Return preference",
            min_value=1, max_value=5, value=3,
            help="1 = preserve capital (2–4 %/yr)  ·  5 = maximum growth (12–15 %+/yr)",
            label_visibility="collapsed",
            key="pb_return",
        )
        return_labels = {
            1: "Capital preservation (1–4 %/yr)",
            2: "Low growth (4–6 %/yr)",
            3: "Moderate growth (6–9 %/yr)",
            4: "High growth (9–12 %/yr)",
            5: "Maximum growth (12–15 %+/yr)",
        }
        st.caption(return_labels[return_pref])

    with col_v:
        st.markdown("**〰️ Volatility Tolerance**")
        st.caption("How much short-term price fluctuation can you accept?")
        vol_pref = st.slider(
            "Volatility tolerance",
            min_value=1, max_value=5, value=3,
            help="1 = very low (5–9 %)  ·  5 = very high (20–35 %)",
            label_visibility="collapsed",
            key="pb_vol",
        )
        vol_labels = {
            1: "Very low (5–9 % ann.)",
            2: "Low (8–12 % ann.)",
            3: "Moderate (11–16 % ann.)",
            4: "High (15–21 % ann.)",
            5: "Very high (19–35 % ann.)",
        }
        st.caption(vol_labels[vol_pref])

    with col_d:
        st.markdown("**📉 Drawdown Tolerance**")
        st.caption("What is the largest temporary loss you could endure without selling?")
        dd_pref = st.slider(
            "Drawdown tolerance",
            min_value=1, max_value=5, value=3,
            help="1 = very low (max −10 %)  ·  5 = very high (−40 to −60 %)",
            label_visibility="collapsed",
            key="pb_dd",
        )
        dd_labels = {
            1: "Very conservative (max −10 %)",
            2: "Conservative (max −20 %)",
            3: "Moderate (max −32 %)",
            4: "Aggressive (max −45 %)",
            5: "Very aggressive (−60 % or more)",
        }
        st.caption(dd_labels[dd_pref])

    st.divider()

    # ── 3. Dynamic hints ───────────────────────────────────────────────────────
    _dynamic_hints(return_pref, vol_pref, dd_pref)

    # ── 4. Score all presets and sort ─────────────────────────────────────────
    ranked = sorted(
        [
            (preset, _score_preset(preset, return_pref, vol_pref, dd_pref))
            for preset in _PRESETS
        ],
        key=lambda x: x[1]["total"],
        reverse=True,
    )

    # ── 5. Recommended portfolios (top 3) ─────────────────────────────────────
    st.subheader("Recommended Portfolios")
    st.markdown(
        "Based on your preferences, these are the three best-matching portfolio profiles. "
        "Scores are computed per dimension (0–10) against the target ranges "
        "implied by your slider settings."
    )

    for rank, (preset, scores) in enumerate(ranked[:3], start=1):
        _render_recommendation(rank, preset, scores)
        st.write("")

    # ── 6. Score transparency note ────────────────────────────────────────────
    with st.expander("How are scores calculated?", expanded=False):
        st.markdown(
            """
Each portfolio is scored on three independent dimensions based on its approximate
long-run historical characteristics:

| Dimension | What is compared |
|-----------|-----------------|
| **Return score** | Portfolio's expected annual return vs your target range |
| **Volatility score** | Portfolio's annualized volatility vs your tolerance range |
| **Drawdown score** | Portfolio's historical max drawdown vs your acceptable loss range |

Scoring rules:
- Full **10/10** if the portfolio's value falls within your target range.
- Score decreases linearly the further outside the range it falls.
- **Overall match** = average of the three dimension scores, scaled to 0–100 %.

Portfolio characteristics are based on approximate long-run historical averages
and will differ across specific time periods.
            """
        )

    # ── 7. Disclaimer ─────────────────────────────────────────────────────────
    st.divider()
    st.caption(
        "⚠️ **Disclaimer:** All results are based on approximate historical data and "
        "should not be considered investment advice. Past performance is not indicative "
        "of future results. Consult a qualified financial advisor before making investment decisions."
    )
