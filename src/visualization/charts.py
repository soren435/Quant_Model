"""
Plotly chart builders. Each function returns a go.Figure ready for st.plotly_chart().
All charts share a consistent clean layout and color palette.
"""
import plotly.graph_objects as go
import pandas as pd
import numpy as np

# ── Palette ────────────────────────────────────────────────────────────────────

COLORS = [
    "#2563EB",  # blue
    "#DC2626",  # red
    "#16A34A",  # green
    "#9333EA",  # purple
    "#F59E0B",  # amber
    "#0891B2",  # cyan
    "#BE185D",  # pink
    "#065F46",  # dark green
]

FILL_COLORS = [
    "rgba(37,99,235,0.12)",
    "rgba(220,38,38,0.12)",
    "rgba(22,163,74,0.12)",
    "rgba(147,51,234,0.12)",
    "rgba(245,158,11,0.12)",
    "rgba(8,145,178,0.12)",
]

_AXIS = dict(gridcolor="#E2E8F0", linecolor="#CBD5E1", zeroline=False, showgrid=True)

_BASE = dict(
    plot_bgcolor="white",
    paper_bgcolor="white",
    font=dict(family="sans-serif", color="#1E293B", size=12),
    xaxis=_AXIS,
    yaxis=_AXIS,
    legend=dict(
        bgcolor="rgba(255,255,255,0.9)",
        bordercolor="#E2E8F0",
        borderwidth=1,
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
    ),
    hovermode="x unified",
    margin=dict(l=10, r=10, t=50, b=10),
)


def _layout(title: str = "", **overrides) -> go.Layout:
    cfg = dict(**_BASE, title=dict(text=title, font=dict(size=14, color="#1E293B")))
    cfg.update(overrides)
    return go.Layout(**cfg)


# ── Price & returns ────────────────────────────────────────────────────────────

def plot_price_history(
    prices: pd.DataFrame,
    title: str = "Price History (Indexed, Base = 100)",
    normalize: bool = True,
) -> go.Figure:
    """Normalized (or raw) price history for one or more tickers."""
    fig = go.Figure(layout=_layout(title))
    data = prices.copy()
    if normalize and not data.empty:
        data = data / data.iloc[0] * 100

    for i, col in enumerate(data.columns):
        fig.add_trace(go.Scatter(
            x=data.index,
            y=data[col],
            name=col,
            line=dict(color=COLORS[i % len(COLORS)], width=2),
            hovertemplate=f"<b>{col}</b>: %{{y:.1f}}<extra></extra>",
        ))

    fig.update_yaxes(title_text="Indexed value (base = 100)" if normalize else "Price")
    return fig


def plot_cumulative_returns(
    cum_returns: pd.DataFrame | pd.Series,
    title: str = "Cumulative Returns",
) -> go.Figure:
    """Line chart of cumulative portfolio value (1.0 = start)."""
    fig = go.Figure(layout=_layout(title))

    if isinstance(cum_returns, pd.Series):
        cum_returns = cum_returns.to_frame()

    for i, col in enumerate(cum_returns.columns):
        s = cum_returns[col]
        fig.add_trace(go.Scatter(
            x=s.index,
            y=s,
            name=col,
            line=dict(color=COLORS[i % len(COLORS)], width=2),
            hovertemplate=f"<b>{col}</b>: %{{y:.3f}}x<extra></extra>",
        ))

    fig.update_yaxes(title_text="Value (start = 1.0×)")
    return fig


def plot_drawdown(
    drawdown: pd.DataFrame | pd.Series,
    title: str = "Drawdown",
) -> go.Figure:
    """Filled area chart of drawdown (fractions displayed as %)."""
    fig = go.Figure(layout=_layout(title))

    if isinstance(drawdown, pd.Series):
        drawdown = drawdown.to_frame()

    for i, col in enumerate(drawdown.columns):
        s = drawdown[col] * 100
        fig.add_trace(go.Scatter(
            x=s.index,
            y=s,
            name=col,
            fill="tozeroy",
            fillcolor=FILL_COLORS[i % len(FILL_COLORS)],
            line=dict(color=COLORS[i % len(COLORS)], width=1.5),
            hovertemplate=f"<b>{col}</b>: %{{y:.2f}}%<extra></extra>",
        ))

    fig.update_yaxes(title_text="Drawdown (%)", ticksuffix="%")
    return fig


def plot_rolling_metric(
    series: pd.DataFrame | pd.Series,
    title: str = "Rolling Metric",
    y_label: str = "",
    as_pct: bool = False,
) -> go.Figure:
    """Generic line chart for rolling metrics (volatility, returns, etc.)."""
    fig = go.Figure(layout=_layout(title))

    if isinstance(series, pd.Series):
        series = series.to_frame()

    for i, col in enumerate(series.columns):
        y = series[col] * 100 if as_pct else series[col]
        suffix = "%" if as_pct else ""
        fig.add_trace(go.Scatter(
            x=y.index,
            y=y,
            name=col,
            line=dict(color=COLORS[i % len(COLORS)], width=2),
            hovertemplate=f"<b>{col}</b>: %{{y:.2f}}{suffix}<extra></extra>",
        ))

    if y_label:
        fig.update_yaxes(title_text=y_label)
    if as_pct:
        fig.update_yaxes(ticksuffix="%")

    return fig


# ── Allocation & attribution ───────────────────────────────────────────────────

def plot_allocation_pie(
    weights: dict[str, float],
    title: str = "Portfolio Allocation",
) -> go.Figure:
    """Donut chart of portfolio weights."""
    labels = list(weights.keys())
    values = [weights[k] * 100 for k in labels]

    fig = go.Figure(
        data=go.Pie(
            labels=labels,
            values=values,
            hole=0.42,
            marker=dict(colors=COLORS[: len(labels)]),
            textinfo="label+percent",
            hovertemplate="<b>%{label}</b>: %{value:.1f}%<extra></extra>",
        ),
        layout=_layout(title),
    )
    fig.update_layout(
        legend=dict(orientation="v", x=1.0, y=0.5),
        hovermode=False,
    )
    return fig


def plot_contribution_bar(
    contributions: dict[str, float],
    title: str = "Return Contribution by Asset",
) -> go.Figure:
    """
    Horizontal bar chart showing each asset's contribution to total portfolio return.
    Green = positive contributor, red = negative contributor.
    """
    tickers = list(contributions.keys())
    values = [contributions[t] * 100 for t in tickers]
    bar_colors = [COLORS[2] if v >= 0 else COLORS[1] for v in values]

    fig = go.Figure(
        data=go.Bar(
            x=values,
            y=tickers,
            orientation="h",
            marker_color=bar_colors,
            text=[f"{v:+.2f}%" for v in values],
            textposition="outside",
            hovertemplate="<b>%{y}</b>: %{x:+.2f}%<extra></extra>",
        ),
        layout=_layout(title),
    )
    fig.update_xaxes(title_text="Contribution to Return (%)", ticksuffix="%")
    fig.update_layout(showlegend=False)
    return fig


# ── Correlation ────────────────────────────────────────────────────────────────

def plot_correlation_heatmap(
    corr: pd.DataFrame,
    title: str = "Correlation Matrix",
) -> go.Figure:
    """Annotated heatmap of a correlation matrix."""
    fig = go.Figure(
        data=go.Heatmap(
            z=corr.values,
            x=list(corr.columns),
            y=list(corr.index),
            colorscale="RdBu",
            zmid=0,
            zmin=-1,
            zmax=1,
            text=np.round(corr.values, 2),
            texttemplate="%{text}",
            textfont=dict(size=12),
            hovertemplate="%{y} / %{x}: %{z:.3f}<extra></extra>",
        ),
        layout=_layout(title),
    )
    fig.update_layout(
        xaxis=dict(gridcolor="white", linecolor="white"),
        yaxis=dict(gridcolor="white", linecolor="white"),
    )
    return fig


# ── Single-asset specific ──────────────────────────────────────────────────────

def plot_moving_averages(
    prices: pd.Series,
    ma_short: int = 50,
    ma_long: int = 200,
    ticker: str = "",
) -> go.Figure:
    """Price chart with short and long moving averages."""
    label = (
        f"{ticker} — Price with {ma_short} & {ma_long}-day MA"
        if ticker
        else "Price with Moving Averages"
    )
    fig = go.Figure(layout=_layout(label))

    fig.add_trace(go.Scatter(
        x=prices.index, y=prices,
        name="Price",
        line=dict(color=COLORS[0], width=2),
        hovertemplate="Price: %{y:.2f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=prices.index, y=prices.rolling(ma_short).mean(),
        name=f"{ma_short}-day MA",
        line=dict(color=COLORS[2], width=1.5, dash="dash"),
        hovertemplate=f"{ma_short}MA: %{{y:.2f}}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=prices.index, y=prices.rolling(ma_long).mean(),
        name=f"{ma_long}-day MA",
        line=dict(color=COLORS[1], width=1.5, dash="dot"),
        hovertemplate=f"{ma_long}MA: %{{y:.2f}}<extra></extra>",
    ))

    fig.update_yaxes(title_text="Price")
    return fig


def plot_monthly_returns_heatmap(
    returns: pd.Series,
    title: str = "Monthly Returns (%)",
) -> go.Figure:
    """Calendar heatmap: rows = years, columns = months."""
    monthly = returns.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    df = monthly.to_frame("ret")
    df["year"] = df.index.year
    df["month"] = df.index.month

    pivot = df.pivot(index="year", columns="month", values="ret")
    month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    pivot.columns = [month_labels[m - 1] for m in pivot.columns]

    text_vals = (pivot * 100).round(1).astype(str) + "%"
    text_vals = text_vals.where(pivot.notna(), "")

    fig = go.Figure(
        data=go.Heatmap(
            z=pivot.values * 100,
            x=list(pivot.columns),
            y=[str(y) for y in pivot.index],
            colorscale="RdYlGn",
            zmid=0,
            text=text_vals.values,
            texttemplate="%{text}",
            textfont=dict(size=10),
            hovertemplate="<b>%{y} %{x}</b>: %{z:.1f}%<extra></extra>",
            colorbar=dict(title="%"),
        ),
        layout=_layout(title),
    )
    fig.update_layout(
        yaxis=dict(autorange="reversed", gridcolor="white", linecolor="white"),
        xaxis=dict(gridcolor="white", linecolor="white"),
    )
    return fig


def plot_bar_returns(
    stats_dict: dict[str, dict],
    metric: str = "Annualized Return",
    title: str = "",
) -> go.Figure:
    """Horizontal bar chart comparing a single metric across strategies."""
    title = title or f"{metric} Comparison"
    names = list(stats_dict.keys())
    values = [stats_dict[n].get(metric, 0) * 100 for n in names]
    bar_colors = [COLORS[2] if v >= 0 else COLORS[1] for v in values]

    fig = go.Figure(
        data=go.Bar(
            x=values,
            y=names,
            orientation="h",
            marker_color=bar_colors,
            text=[f"{v:.1f}%" for v in values],
            textposition="outside",
            hovertemplate="<b>%{y}</b>: %{x:.2f}%<extra></extra>",
        ),
        layout=_layout(title),
    )
    fig.update_xaxes(title_text=metric, ticksuffix="%")
    fig.update_layout(showlegend=False)
    return fig


# ── Efficient Frontier ─────────────────────────────────────────────────────────

def plot_efficient_frontier(
    ef_result: dict,
    profile_vol:    float | None = None,
    profile_ret:    float | None = None,
    profile_label:  str = "Your Profile",
    title: str = "Efficient Frontier",
) -> go.Figure:
    """
    Scatter plot of random portfolios coloured by Sharpe ratio,
    with Max Sharpe, Min Vol, and optional target-vol portfolios highlighted.

    Args:
        ef_result:    Dict returned by efficient_frontier().
        profile_vol:  Annualised vol of the investor's current profile allocation.
        profile_ret:  Annualised return of the investor's current profile allocation.
        profile_label: Label for the profile dot.
    """
    frontier = ef_result.get("frontier")
    if frontier is None or frontier.empty:
        return go.Figure()

    fig = go.Figure(layout=_layout(title))

    # Random portfolio cloud — coloured by Sharpe
    fig.add_trace(go.Scatter(
        x=frontier["vol"] * 100,
        y=frontier["ret"] * 100,
        mode="markers",
        marker=dict(
            size=5,
            color=frontier["sharpe"],
            colorscale="Viridis",
            showscale=True,
            colorbar=dict(title="Sharpe", thickness=12, len=0.6),
            opacity=0.6,
        ),
        name="Random portfolios",
        hovertemplate="Vol: %{x:.1f}%  Ret: %{y:.1f}%<extra></extra>",
    ))

    # Special portfolios
    specials = [
        ("max_sharpe", "⭐ Max Sharpe",  COLORS[2], "star",    14),
        ("min_vol",    "🛡 Min Vol",      COLORS[0], "diamond", 12),
        ("target_vol", "🎯 Target Vol",   COLORS[4], "circle",  12),
    ]
    for key, label, color, symbol, size in specials:
        port = ef_result.get(key)
        if not port:
            continue
        fig.add_trace(go.Scatter(
            x=[port["vol"] * 100],
            y=[port["ret"] * 100],
            mode="markers+text",
            marker=dict(size=size, color=color, symbol=symbol,
                        line=dict(width=2, color="white")),
            text=[label],
            textposition="top center",
            textfont=dict(size=10, color=color),
            name=label,
            hovertemplate=(
                f"<b>{label}</b><br>"
                f"Vol: {port['vol']*100:.1f}%<br>"
                f"Return: {port['ret']*100:.1f}%<br>"
                f"Sharpe: {port['sharpe']:.2f}"
                "<extra></extra>"
            ),
        ))

    # Current profile allocation dot
    if profile_vol is not None and profile_ret is not None:
        fig.add_trace(go.Scatter(
            x=[profile_vol * 100],
            y=[profile_ret * 100],
            mode="markers+text",
            marker=dict(size=14, color=COLORS[1], symbol="x",
                        line=dict(width=2, color="white")),
            text=[profile_label],
            textposition="top center",
            textfont=dict(size=10, color=COLORS[1]),
            name=profile_label,
            hovertemplate=(
                f"<b>{profile_label}</b><br>"
                f"Vol: {profile_vol*100:.1f}%<br>"
                f"Return: {profile_ret*100:.1f}%"
                "<extra></extra>"
            ),
        ))

    fig.update_xaxes(title_text="Annualised Volatility (%)", ticksuffix="%")
    fig.update_yaxes(title_text="Annualised Return (%)",     ticksuffix="%")
    return fig
