"""
stats_pitching.py
──────────────────
Pitcher-side equivalent of stats.py. Reuses several generic functions from
stats.py directly (they don't care whether the pitch log came from filtering
on batter_id or pitcher_id) — see app.py / pages/1_Pitcher_Dashboard.py for
which ones get reused as-is (compute_pitch_type_table, discipline_heatmap-
feeding logic, ev_la data prep, count matrix).

Key design choice: ERA/WHIP/W-L/IP come from the OFFICIAL per-player season
stats endpoint (data_layer.get_pitcher_official_season_stats), not derived
from the pitch-by-pitch feed — earned vs. unearned runs is an official
scorer's judgment call that isn't reliably recoverable from play-by-play
data. Everything in this file that DOES use the pitch-by-pitch log is for
metrics that genuinely need pitch-level detail: pitch mix, velocity,
movement, plate discipline induced, contact quality allowed, and splits.
"""

import numpy as np
import pandas as pd

from stats import HIT_EVENTS, NON_AB_EVENTS, WALK_EVENTS, is_non_pa_event, _bool, _safe_div  # reuse, not redefine

# For a pitcher, "whiff"/"chase" induced are GOOD outcomes — opposite framing
# from the hitter's own version of the same fields. Kept in a dedicated table
# here so the direction is never accidentally shared/confused with stats.py.
PITCHING_PERCENTILE_METRICS = [
    # (label, official/derived key, standard-pool column, savant-pool column, higher_is_better)
    ("ERA", "era", "era", "era", False),
    ("WHIP", "whip", "whip", None, False),
    ("K%", "k_pct", "k_pct", "k_pct_savant", True),
    ("BB%", "bb_pct", "bb_pct", "bb_pct_savant", False),
    ("K-BB%", "k_bb_pct", "k_bb_pct", None, True),
    ("HR/9", "hr_per_9", "hr_per_9", None, False),
    ("FIP (approx)", "fip", "fip", None, False),
    ("Whiff% (induced)", "whiff_pct", None, "whiff_pct", True),
    ("Chase% (induced)", "chase_pct", None, "chase_pct", True),
    ("Hard-Hit% (against)", "hard_hit_pct_against", None, "hard_hit_pct_against", False),
    ("Avg Exit Velo (against)", "avg_ev_against", None, "avg_ev_against", False),
    ("Sweet-Spot% (against)", "sweet_spot_pct_against", None, "sweet_spot_pct_against", False),
]


def compute_pitch_velocity_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per pitch type: usage%, avg/max velo, avg spin rate, avg induced
    vertical break (ivb), avg horizontal break (hb), avg release extension."""
    if df is None or df.empty or "pitch_description" not in df.columns:
        return pd.DataFrame()

    from stats import PITCH_COLORS, shorten_pitch  # local import avoids a cycle

    total = len(df)
    rows = []
    for pdesc, grp in df.groupby("pitch_description"):
        rows.append({
            "pitch_type": shorten_pitch(pdesc),
            "color": PITCH_COLORS.get(str(pdesc), "#AAAAAA"),
            "n_pitches": len(grp),
            "usage_pct": _safe_div(len(grp), total) * 100,
            "avg_velo": grp["start_speed"].mean(),
            "max_velo": grp["start_speed"].max(),
            "avg_spin": grp["spin_rate"].mean() if "spin_rate" in grp.columns else np.nan,
            "avg_ivb": grp["ivb"].mean() if "ivb" in grp.columns else np.nan,
            "avg_hb": grp["hb"].mean() if "hb" in grp.columns else np.nan,
            "avg_extension": grp["extension"].mean() if "extension" in grp.columns else np.nan,
        })
    return pd.DataFrame(rows).sort_values("n_pitches", ascending=False, ignore_index=True)


def get_pitcher_start_game_ids(df: pd.DataFrame) -> set:
    """Which of this pitcher's games he STARTED, as opposed to appeared in
    relief — determined from the data itself (whether his earliest recorded
    inning in that game is inning 1), not a separate official field, since
    the per-pitch feed doesn't carry a "started this game" flag directly.
    A relief appearance essentially never begins in the 1st inning, so this
    is a reliable proxy; the rare "opener" bulk-reliever case (a true
    reliever brought in during the 1st inning by design) would be
    misclassified as a start, but that's an edge case this doesn't attempt
    to handle specially.
    """
    if df is None or df.empty or "inning" not in df.columns or "game_id" not in df.columns:
        return set()
    first_inning_per_game = df.groupby("game_id")["inning"].min()
    return set(first_inning_per_game[first_inning_per_game == 1].index)


def compute_pitcher_splits(df: pd.DataFrame) -> dict:
    """Splits by the OPPOSING batter's handedness (what matters for a
    pitcher), plus home/away if attach_home_away(..., team_id_col=
    'pitcher_team_id') was applied upstream."""
    from stats import compute_slash_line  # opponent's batting line against this pitcher

    if df is None or df.empty:
        return {}
    splits = {}
    if "batter_hand" in df.columns:
        for hand, label in [("L", "vs LHH"), ("R", "vs RHH")]:
            splits[label] = compute_slash_line(df[df["batter_hand"] == hand])
    if "is_home" in df.columns:
        splits["Home"] = compute_slash_line(df[df["is_home"] == True])  # noqa: E712
        splits["Away"] = compute_slash_line(df[df["is_home"] == False])  # noqa: E712
    return splits


def compute_pitcher_rolling_trend(df: pd.DataFrame, window: int = 25) -> pd.DataFrame:
    """Rolling opponent-AVG-against, K%, BB%, and Whiff%-induced across the
    season. (Not rolling ERA — earned-run attribution isn't available at
    pitch-event granularity, see module docstring.)"""
    if df is None or df.empty:
        return pd.DataFrame()

    pa_df = df[df["event_type"].notna()].copy()
    pa_df = pa_df[~is_non_pa_event(pa_df["event_type"])]
    if pa_df.empty:
        return pd.DataFrame()

    pa_df["game_date"] = pd.to_datetime(pa_df["game_date"])
    pa_df.sort_values(["game_date", "ab_number"], inplace=True)

    pa_df["is_ab"] = ~pa_df["event_type"].isin(NON_AB_EVENTS)
    pa_df["is_hit"] = pa_df["event_type"].isin(HIT_EVENTS)
    pa_df["is_k"] = pa_df["event_type"].isin(["strikeout", "strikeout_double_play"])
    pa_df["is_bb"] = pa_df["event_type"].isin(WALK_EVENTS)

    pa_df["roll_hits"] = pa_df["is_hit"].rolling(window, min_periods=5).sum()
    pa_df["roll_ab"] = pa_df["is_ab"].rolling(window, min_periods=5).sum()
    pa_df["roll_avg_against"] = pa_df["roll_hits"] / pa_df["roll_ab"]
    pa_df["roll_k_pct"] = pa_df["is_k"].rolling(window, min_periods=5).mean() * 100
    pa_df["roll_bb_pct"] = pa_df["is_bb"].rolling(window, min_periods=5).mean() * 100

    return pa_df[["game_date", "roll_avg_against", "roll_k_pct", "roll_bb_pct"]].dropna(
        how="all", subset=["roll_avg_against"]
    )


def compute_pitch_mix_by_count(df: pd.DataFrame) -> pd.DataFrame:
    """Usage% of each pitch type, broken out by ball-strike count situation
    (ahead/even/behind) — a real scouting question: what do they throw when
    they need a strike vs. when they're ahead and can expand the zone."""
    if df is None or df.empty or "pitch_description" not in df.columns:
        return pd.DataFrame()

    from stats import shorten_pitch

    d = df.copy()

    def situation(row):
        b, s = row["balls"], row["strikes"]
        if pd.isna(b) or pd.isna(s):
            return None
        if s > b:
            return "Ahead (pitcher)"
        if b > s:
            return "Behind (pitcher)"
        return "Even"

    d["situation"] = d.apply(situation, axis=1)
    d["pitch_type"] = d["pitch_description"].apply(shorten_pitch)

    table = (
        d.groupby(["situation", "pitch_type"]).size().rename("n").reset_index()
    )
    totals = table.groupby("situation")["n"].transform("sum")
    table["usage_pct"] = table["n"] / totals * 100
    return table


def build_pitching_percentile_table(
    pitcher_stats: dict,
    standard_pool: pd.DataFrame,
    savant_pool: pd.DataFrame,
    is_mlb: bool,
    use_relief_pool: bool = False,
) -> pd.DataFrame:
    """Same shape/logic as stats.build_percentile_table, but pitching-specific
    metric directions, and an adaptive qualified/relief comparison pool:
    a full-time reliever will basically never clear the official 1-IP-per-
    team-game qualified bar, so if their own IP is below that bar we compare
    them against a much lower relief_pool floor instead — see
    data_layer.get_pitching_standard_leaderboard for how that floor is set."""
    from data_layer import percentile_rank

    rows = []
    for label, key, std_col, savant_col, higher_is_better in PITCHING_PERCENTILE_METRICS:
        value = pitcher_stats.get(key)
        pct = None
        source = None

        if std_col and standard_pool is not None and not standard_pool.empty and std_col in standard_pool.columns:
            pool_mask = standard_pool["relief_pool"] if use_relief_pool else standard_pool["qualified"]
            pool = standard_pool[pool_mask]
            pct = percentile_rank(value, pool[std_col])
            source = "league (relief-eligible)" if use_relief_pool else "league (qualified)"
        elif is_mlb and savant_col and savant_pool is not None and not savant_pool.empty and savant_col in savant_pool.columns:
            pct = percentile_rank(value, savant_pool[savant_col])
            source = "MLB Statcast (qualified)"

        if pct is not None and not higher_is_better:
            pct = 100 - pct

        rows.append({"metric": label, "value": value, "percentile": pct, "source": source})
    return pd.DataFrame(rows)
