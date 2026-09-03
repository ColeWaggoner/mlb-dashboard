"""
period_ui.py
────────────
Shared "Full Season / Last N Games / Custom Range" selector used by all
three dashboards. Kept separate from theme.py since this is a stateful
widget with real logic (bounds-checking dates against the loaded data),
not just styling.
"""

from datetime import date

import pandas as pd
import streamlit as st


def period_selector(key_prefix: str, df: pd.DataFrame, unit_label: str = "Games",
                     count_df: pd.DataFrame = None) -> dict:
    """Renders the period-selector row and returns a dict ready to pass
    straight to stats.filter_by_period(df, **result). Bounds the "Last N
    {unit_label}" input and the custom date pickers to what's actually in
    df, so it's not possible to pick a range with zero games in it.

    unit_label: what to call one unit in the "Last N ___" control — e.g.
    "Starts" on the Pitcher Dashboard instead of the generic "Games".
    count_df: if given, used instead of df to determine how many units are
    available (and thus the max N) — e.g. a starts-only subset, so the
    input's upper bound reflects "how many starts he has", not "how many
    games he's appeared in at all".
    """
    result = {"period": "full", "last_n_games": None, "start_date": None, "end_date": None}
    if df is None or df.empty or "game_date" not in df.columns:
        return result

    dates = pd.to_datetime(df["game_date"])
    min_date, max_date = dates.min().date(), dates.max().date()
    basis = count_df if count_df is not None else df
    n_available = basis["game_id"].nunique() if basis is not None and "game_id" in basis.columns else 0

    col1, col2, col3 = st.columns([1.2, 1, 2])
    with col1:
        choice = st.selectbox(
            "Period", ["Full Season", f"Last N {unit_label}", "Custom Range"],
            key=f"{key_prefix}_period_choice",
        )

    if choice == f"Last N {unit_label}":
        with col2:
            n = st.number_input(
                unit_label, min_value=1, max_value=max(n_available, 1),
                value=min(10, max(n_available, 1)), step=1,
                key=f"{key_prefix}_period_n",
            )
        result["period"] = "last_n"
        result["last_n_games"] = int(n)
    elif choice == "Custom Range":
        with col2:
            start = st.date_input("Start", value=min_date, min_value=min_date, max_value=max_date,
                                   key=f"{key_prefix}_period_start")
        with col3:
            end = st.date_input("End", value=max_date, min_value=min_date, max_value=max_date,
                                 key=f"{key_prefix}_period_end")
        result["period"] = "custom"
        result["start_date"] = start
        result["end_date"] = end

    return result
