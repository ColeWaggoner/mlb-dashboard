"""
stats_team.py
──────────────
Team-level percentile tables, built the same way as the batter/pitcher
versions but comparing one team's aggregate line against every other team
at that level, instead of one player against qualified peers.
"""

import numpy as np
import pandas as pd

TEAM_HITTING_PERCENTILE_METRICS = [
    # (label, column, higher_is_better)
    ("Runs/Game", "runs_per_game", True),
    ("AVG", "avg", True),
    ("OBP", "obp", True),
    ("SLG", "slg", True),
    ("OPS", "ops", True),
    ("HR", "home_runs", True),
    ("K%", "k_pct", False),
    ("BB%", "bb_pct", True),
]

TEAM_PITCHING_PERCENTILE_METRICS = [
    ("ERA", "era", False),
    ("WHIP", "whip", False),
    ("Runs Allowed/Game", "runs_allowed_per_game", False),
    ("K%", "k_pct", True),
    ("BB%", "bb_pct", False),
    ("Saves", "saves", True),
]

TEAM_STATCAST_HITTING_METRICS = [
    ("Hard-Hit%", "hard_hit_pct", True),
    ("Avg Exit Velo", "avg_ev", True),
    ("Chase%", "chase_pct", False),
    ("Whiff%", "whiff_pct", False),
    ("Sweet-Spot%", "sweet_spot_pct", True),
]

TEAM_STATCAST_PITCHING_METRICS = [
    ("Whiff% (induced)", "whiff_pct", True),
    ("Chase% (induced)", "chase_pct", True),
    ("Hard-Hit% (against)", "hard_hit_pct_against", False),
    ("Avg Exit Velo (against)", "avg_ev_against", False),
]


def build_team_percentile_table(team_row: dict, league_pool: pd.DataFrame, metrics: list) -> pd.DataFrame:
    """Generic team-vs-all-other-teams percentile builder — same shape as the
    player-level percentile tables so charts.percentile_bars() can be reused
    as-is."""
    from data_layer import percentile_rank

    rows = []
    for label, col, higher_is_better in metrics:
        value = team_row.get(col)
        pct = None
        if league_pool is not None and not league_pool.empty and col in league_pool.columns:
            pct = percentile_rank(value, league_pool[col])
        if pct is not None and not higher_is_better:
            pct = 100 - pct
        rows.append({"metric": label, "value": value, "percentile": pct,
                      "source": "vs all teams" if pct is not None else None})
    return pd.DataFrame(rows)


def rank_and_format(df: pd.DataFrame, sort_col: str, ascending: bool = False) -> pd.DataFrame:
    """Adds a 1-indexed Rank column based on sort_col, sorted accordingly —
    used for both the team-vs-league table and the roster leaderboards."""
    if df is None or df.empty or sort_col not in df.columns:
        return df
    out = df.sort_values(sort_col, ascending=ascending, na_position="last").reset_index(drop=True)
    out.insert(0, "Rank", np.arange(1, len(out) + 1))
    return out
