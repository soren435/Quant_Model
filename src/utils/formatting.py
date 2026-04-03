"""Formatting, parsing, and common display helpers. No Streamlit dependency."""
import pandas as pd
import numpy as np


def format_pct(value: float, decimals: int = 2) -> str:
    """Format a float as a percentage string, e.g. 0.123 → '12.30%'."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "N/A"
    return f"{value * 100:.{decimals}f}%"


def format_number(value: float, decimals: int = 2) -> str:
    """Format a float as a plain number string, e.g. 1.234 → '1.23'."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "N/A"
    return f"{value:.{decimals}f}"


def parse_tickers(input_str: str) -> list[str]:
    """Parse a comma-separated ticker string into a clean uppercase list."""
    if not input_str or not input_str.strip():
        return []
    return [t.strip().upper() for t in input_str.split(",") if t.strip()]


def parse_weights(input_str: str, n: int) -> list[float] | None:
    """
    Parse comma-separated weights and normalize them to sum to 1.0.
    Accepts integers (e.g. '60, 40') or decimals (e.g. '0.6, 0.4').

    Returns:
        Normalized list of floats, or None if parsing fails or count mismatches.
    """
    if not input_str or not input_str.strip():
        return None
    try:
        weights = [float(w.strip()) for w in input_str.split(",") if w.strip()]
        if len(weights) != n:
            return None
        if any(w < 0 for w in weights):
            return None
        total = sum(weights)
        if total <= 0:
            return None
        return [w / total for w in weights]
    except ValueError:
        return None


def date_to_str(d) -> str:
    """Convert a date object or string to 'YYYY-MM-DD' string."""
    if isinstance(d, str):
        return d
    return d.strftime("%Y-%m-%d")


def get_period_label(start: str, end: str) -> str:
    """Return a human-readable period label, e.g. '5.2 years' or '8 months'."""
    start_dt = pd.to_datetime(start)
    end_dt = pd.to_datetime(end)
    years = (end_dt - start_dt).days / 365.25
    if years >= 1:
        return f"{years:.1f} years"
    months = (end_dt - start_dt).days / 30.44
    return f"{months:.0f} months"
