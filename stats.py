"""
stats.py
────────
Pure computation functions. Nothing here touches the network — everything
takes a pandas DataFrame of pitch-level events (the output of
data_layer.get_batter_pitch_log) and returns stats dicts / small DataFrames
for the charts and tables in app.py.
"""

import numpy as np
import pandas as pd

# ── Shared constants (kept identical to the original notebook) ──────────────

HIT_EVENTS = ["single", "double", "triple", "home_run"]
NON_AB_EVENTS = [
    "walk", "intent_walk", "hit_by_pitch", "sac_fly", "sac_bunt",
    "catcher_interf", "sac_fly_double_play", "sac_bunt_double_play",
]
WALK_EVENTS = ["walk", "intent_walk"]

# Baserunning/administrative outcomes that MLB's feed can attach to a
# batter's at-bat entry (result.type == 'atBat') even though nothing about
# them is actually the batter's own plate-appearance result — e.g. a runner
# caught stealing for the 3rd out while the batter's own count was still
# in progress. These carry event_type but must never be counted as a PA or
# AB. Found directly from a user-supplied raw data export showing
# 'caught_stealing_2b' rows inflating both PA and AB counts (exact-prefix
# variants for other bases, e.g. caught_stealing_3b/home, are covered by
# the prefix check in is_non_pa_event() below rather than enumerated here).
NON_PA_EVENT_PREFIXES = ("caught_stealing", "pickoff", "stolen_base")
NON_PA_EVENT_EXACT = {
    "wild_pitch", "passed_ball", "balk", "defensive_indiff",
    "ejection", "no_pitch", "game_advisory", "runner_double_play",
}
SZ_LEFT, SZ_RIGHT = -0.8333, 0.8333


def is_non_pa_event(event_type_series: pd.Series) -> pd.Series:
    """True for rows whose event_type is a baserunning/administrative
    outcome, not a genuine plate-appearance result — see NON_PA_EVENT_*
    above. Rows matching this should be excluded from PA/AB (and
    everything downstream of them), but are NOT treated as "missing" a
    plate appearance either — the batter genuinely didn't complete one."""
    s = event_type_series.astype(str)
    return s.isin(NON_PA_EVENT_EXACT) | s.str.startswith(NON_PA_EVENT_PREFIXES)

PITCH_COLORS = {
    "Four-Seam Fastball": "#FF3030", "Two-Seam Fastball": "#FF7700",
    "Sinker": "#FFB700", "Cutter": "#FFE800", "Slider": "#3399FF",
    "Sweeper": "#00CCFF", "Slurve": "#FF00CC", "Curveball": "#00DD55",
    "Knuckle Curve": "#00FFAA", "Slow Curve": "#88FF00", "Changeup": "#CC44FF",
    "Splitter": "#FF6600", "Forkball": "#FF0066", "Screwball": "#FF99FF",
    "Knuckleball": "#AAAAAA", "Eephus": "#FFFFFF",
}

# If pull/oppo comes out backwards for a known dead-pull hitter on your first
# real run, flip this — it's the only thing that depends on the raw hit_x/hit_y
# sign convention, which couldn't be verified without live data.
PULL_SIGN_FLIP = False


def shorten_pitch(name) -> str:
    return str(name).replace("Four-Seam Fastball", "Four-Seam")


def _safe_div(n, d):
    return float(n) / float(d) if d else np.nan


def _bool(series: pd.Series) -> pd.Series:
    """is_swing/is_whiff etc. come through as True/None — coerce to real bools."""
    return series.fillna(False).astype(bool)


def _bb_type(trajectory) -> str:
    if not isinstance(trajectory, str):
        return None
    t = trajectory.lower()
    if "ground" in t:
        return "ground_ball"
    if "fly" in t:
        return "fly_ball"
    if "line" in t:
        return "line_drive"
    if "pop" in t:
        return "popup"
    return "other"


# ─────────────────────────────────────────────────────────────────────────────
# Slash line
# ─────────────────────────────────────────────────────────────────────────────

def compute_duplicate_at_bats(df: pd.DataFrame) -> dict:
    """Diagnostic, not a stat: the mirror image of compute_orphaned_at_bats —
    counts at-bats that have MORE than one row carrying a recorded outcome.
    Should always be 0 after the data_layer dedup fix (duplicate game_ids
    before pulling, plus a row-level dedup as a safety net); a nonzero count
    here means a plate appearance is getting double-counted somewhere,
    which inflates PA/AB/hit totals above the true value — the opposite
    symptom from orphaned at-bats, and the one that showed up as counts
    running slightly HIGH vs an official source.
    """
    if df is None or df.empty or "ab_number" not in df.columns:
        return {"n_duplicated": 0, "n_total_at_bats": 0, "duplicate_examples": []}

    d = df.copy()
    outcome_counts = d.groupby(["game_id", "ab_number"])["event_type"].apply(lambda s: s.notna().sum())
    dup_keys = outcome_counts[outcome_counts > 1].index.tolist()
    examples = []
    for game_id, ab_number in dup_keys[:10]:
        cell = d[(d["game_id"] == game_id) & (d["ab_number"] == ab_number)]
        examples.append({
            "game_id": game_id, "game_date": cell["game_date"].iloc[0] if len(cell) else None,
            "ab_number": ab_number, "n_outcome_rows": int(cell["event_type"].notna().sum()),
        })
    return {
        "n_duplicated": len(dup_keys),
        "n_total_at_bats": len(outcome_counts),
        "duplicate_examples": examples,
    }


def compute_data_completeness_summary(df: pd.DataFrame) -> dict:
    """Diagnostic, not a stat: raw counts of what actually got pulled for this
    player — games, plate appearances, and a breakdown of every event_type
    string present. This exists specifically because the orphaned-at-bat
    check alone isn't enough to catch every possible way a stat line can
    come in low: it only proves individual plate appearances within a
    PULLED game aren't getting silently dropped. If an entire game is
    missing from what get_player_games_list returned in the first place,
    there's nothing in that game for the orphan check to find — this
    surfaces the actual games/PA counts directly so they're comparable
    against an official source rather than trusted blindly.

    n_pa here is the CORRECTED count (matching what compute_slash_line uses
    — excludes baserunning/administrative rows like caught_stealing_2b via
    is_non_pa_event). n_pa_raw and excluded_event_counts show what got
    filtered out and why, so a discrepancy is traceable rather than hidden.
    """
    if df is None or df.empty:
        return {"n_games": 0, "n_pa": 0, "n_pa_raw": 0, "date_min": None, "date_max": None,
                "event_type_counts": {}, "excluded_event_counts": {}}

    n_games = int(df["game_id"].nunique()) if "game_id" in df.columns else 0
    pa_df_raw = df[df["event_type"].notna()] if "event_type" in df.columns else df.iloc[0:0]
    date_min = df["game_date"].min() if "game_date" in df.columns and len(df) else None
    date_max = df["game_date"].max() if "game_date" in df.columns and len(df) else None
    event_counts = pa_df_raw["event_type"].value_counts().to_dict() if len(pa_df_raw) else {}

    if len(pa_df_raw):
        excluded_mask = is_non_pa_event(pa_df_raw["event_type"])
        n_pa = int((~excluded_mask).sum())
        excluded_counts = pa_df_raw.loc[excluded_mask, "event_type"].value_counts().to_dict()
    else:
        n_pa = 0
        excluded_counts = {}

    return {
        "n_games": n_games,
        "n_pa": n_pa,
        "n_pa_raw": len(pa_df_raw),
        "date_min": date_min,
        "date_max": date_max,
        "event_type_counts": event_counts,
        "excluded_event_counts": excluded_counts,
    }


def compute_orphaned_at_bats(df: pd.DataFrame) -> dict:
    """Diagnostic, not a stat: counts at-bats that have pitch-level rows but
    NO row carrying the actual outcome (event_type). After the get_data_df
    fix for the dropped-plate-appearance bug, this should always be 0 — a
    nonzero count here means either that fix isn't actually active for this
    data (stale cache/old code still running) or a different bug is still
    dropping plate appearances. Also reports the raw counts so a support
    conversation doesn't need to speculate about what the underlying numbers
    even are.
    """
    if df is None or df.empty or "ab_number" not in df.columns:
        return {"n_orphaned": 0, "n_total_at_bats": 0, "orphaned_examples": []}

    d = df.copy()
    grouped = d.groupby(["game_id", "ab_number"])["event_type"].apply(lambda s: s.notna().any())
    orphaned_keys = grouped[~grouped].index.tolist()
    examples = []
    for game_id, ab_number in orphaned_keys[:10]:
        cell = d[(d["game_id"] == game_id) & (d["ab_number"] == ab_number)]
        examples.append({
            "game_id": game_id, "game_date": cell["game_date"].iloc[0] if len(cell) else None,
            "ab_number": ab_number, "n_pitch_rows": len(cell),
        })
    return {
        "n_orphaned": len(orphaned_keys),
        "n_total_at_bats": len(grouped),
        "orphaned_examples": examples,
    }


def compute_slash_line(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return _empty_slash_line()

    pa_df = df[df["event_type"].notna()].copy()
    pa_df = pa_df[~is_non_pa_event(pa_df["event_type"])]
    ab_df = pa_df[~pa_df["event_type"].isin(NON_AB_EVENTS)]

    n_pa, n_ab = len(pa_df), len(ab_df)
    n_hits = ab_df["event_type"].isin(HIT_EVENTS).sum()
    n_1b = (ab_df["event_type"] == "single").sum()
    n_2b = (ab_df["event_type"] == "double").sum()
    n_3b = (ab_df["event_type"] == "triple").sum()
    n_hr = (ab_df["event_type"] == "home_run").sum()
    n_bb = pa_df["event_type"].isin(WALK_EVENTS).sum()
    n_hbp = (pa_df["event_type"] == "hit_by_pitch").sum()
    n_sf = pa_df["event_type"].isin(["sac_fly", "sac_fly_double_play"]).sum()
    n_k = pa_df["event_type"].isin(["strikeout", "strikeout_double_play"]).sum()
    tb = n_1b + 2 * n_2b + 3 * n_3b + 4 * n_hr
    n_rbi = int(pa_df["rbi"].fillna(0).sum()) if "rbi" in pa_df.columns else 0

    ba = _safe_div(n_hits, n_ab)
    obp = _safe_div(n_hits + n_bb + n_hbp, n_ab + n_bb + n_hbp + n_sf)
    slg = _safe_div(tb, n_ab)
    ops = (obp or 0) + (slg or 0) if not (np.isnan(ba)) else np.nan
    babip_denom = n_ab - n_k - n_hr + n_sf
    babip = _safe_div(n_hits - n_hr, babip_denom)

    return {
        "n_pa": n_pa, "n_ab": n_ab, "n_hits": n_hits,
        "n_1b": n_1b, "n_2b": n_2b, "n_3b": n_3b, "n_hr": n_hr,
        "n_bb": n_bb, "n_hbp": n_hbp, "n_k": n_k, "tb": tb, "n_rbi": n_rbi,
        "ba": ba, "obp": obp, "slg": slg, "ops": ops,
        "iso": (slg - ba) if not np.isnan(slg) and not np.isnan(ba) else np.nan,
        "babip": babip,
        "k_pct": _safe_div(n_k, n_pa),
        "bb_pct": _safe_div(n_bb, n_pa),
    }


def _empty_slash_line() -> dict:
    keys = ["n_pa", "n_ab", "n_hits", "n_1b", "n_2b", "n_3b", "n_hr", "n_bb",
            "n_hbp", "n_k", "tb", "n_rbi", "ba", "obp", "slg", "ops", "iso", "babip",
            "k_pct", "bb_pct"]
    return {k: (0 if k.startswith("n_") or k == "tb" else np.nan) for k in keys}


# ─────────────────────────────────────────────────────────────────────────────
# Statcast batted-ball summary
# ─────────────────────────────────────────────────────────────────────────────

def compute_statcast_summary(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {"n_bip": 0, "hard_hit_pct": np.nan, "avg_ev": np.nan,
                "max_ev": np.nan, "avg_la": np.nan, "sweet_spot_pct": np.nan}

    bip = df[df["in_play"] == True].copy()  # noqa: E712
    measured = bip[bip["launch_speed"].notna()]
    n_bip = len(measured)
    if n_bip == 0:
        return {"n_bip": 0, "hard_hit_pct": np.nan, "avg_ev": np.nan,
                "max_ev": np.nan, "avg_la": np.nan, "sweet_spot_pct": np.nan}

    hard_hit_pct = _safe_div((measured["launch_speed"] >= 95).sum(), n_bip)
    sweet_spot_pct = _safe_div(
        measured["launch_angle"].between(8, 32).sum(), n_bip
    )
    return {
        "n_bip": n_bip,
        "hard_hit_pct": hard_hit_pct,
        "avg_ev": measured["launch_speed"].mean(),
        "max_ev": measured["launch_speed"].max(),
        "avg_la": measured["launch_angle"].mean(),
        "sweet_spot_pct": sweet_spot_pct,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Plate discipline
# ─────────────────────────────────────────────────────────────────────────────

def compute_plate_discipline(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {k: np.nan for k in [
            "n_pitches", "zone_pct", "swing_pct", "chase_pct", "z_swing_pct",
            "whiff_pct", "swstr_pct", "contact_pct", "csw_pct", "first_pitch_strike_pct",
        ]}

    d = df.copy()
    d["is_swing_b"] = _bool(d["is_swing"])
    d["is_whiff_b"] = _bool(d["is_whiff"])
    n_pitches = len(d)

    if "zone" in d.columns and d["zone"].notna().any():
        in_zone = d["zone"].between(1, 9)
    else:
        in_zone = (
            d["px"].between(SZ_LEFT, SZ_RIGHT) & d["pz"].between(d["sz_bot"], d["sz_top"])
        )
    out_zone = ~in_zone & d["zone"].notna() if "zone" in d.columns else ~in_zone

    n_in_zone = in_zone.sum()
    n_out_zone = out_zone.sum()
    n_swings = d["is_swing_b"].sum()
    n_whiffs = d["is_whiff_b"].sum()

    first_pitch = d[(d["balls"] == 0) & (d["strikes"] == 0)]
    fp_strikes = first_pitch["is_strike"].fillna(False).astype(bool).sum()

    return {
        "n_pitches": n_pitches,
        "zone_pct": _safe_div(n_in_zone, n_pitches),
        "swing_pct": _safe_div(n_swings, n_pitches),
        "chase_pct": _safe_div((d["is_swing_b"] & out_zone).sum(), n_out_zone),
        "z_swing_pct": _safe_div((d["is_swing_b"] & in_zone).sum(), n_in_zone),
        "whiff_pct": _safe_div(n_whiffs, n_swings),
        "swstr_pct": _safe_div(n_whiffs, n_pitches),
        "contact_pct": _safe_div(n_swings - n_whiffs, n_swings),
        "csw_pct": _safe_div(
            d["is_strike"].fillna(False).astype(bool).sum(), n_pitches
        ),
        "first_pitch_strike_pct": _safe_div(fp_strikes, len(first_pitch)),
    }


def _in_zone_mask(d: pd.DataFrame) -> pd.Series:
    """Shared in-zone boolean mask logic, reused by compute_plate_discipline
    and compute_contact_profile so the zone definition never drifts between
    the two."""
    if "zone" in d.columns and d["zone"].notna().any():
        return d["zone"].between(1, 9)
    return d["px"].between(SZ_LEFT, SZ_RIGHT) & d["pz"].between(d["sz_bot"], d["sz_top"])


# ─────────────────────────────────────────────────────────────────────────────
# Batted-ball direction / type profile (also returns enriched df for spray chart)
# ─────────────────────────────────────────────────────────────────────────────

def enrich_spray_coordinates(df: pd.DataFrame, batter_hand: str = "R") -> pd.DataFrame:
    """Adds x_ft, y_ft, spray_angle_deg, pull_side, bb_type columns.

    Uses each row's own batter_hand column when present (so a team-wide
    dataframe with mixed lefties/righties classifies Pull/Center/Opposite
    correctly per batter) — the `batter_hand` argument is only a fallback for
    rows where that column is missing, and for single-player callers that
    don't pass a per-row column at all.
    """
    d = df.copy()
    if "hit_x" not in d.columns or "hit_y" not in d.columns:
        return d

    has_coords = d["hit_x"].notna() & d["hit_y"].notna()
    d["x_ft"] = np.nan
    d["y_ft"] = np.nan
    if has_coords.any():
        max_coord = max(d.loc[has_coords, "hit_x"].abs().max(), d.loc[has_coords, "hit_y"].abs().max())
        if max_coord > 100:
            d.loc[has_coords, "x_ft"] = (d.loc[has_coords, "hit_x"] - 125.42) * 2.4384
            d.loc[has_coords, "y_ft"] = (198.27 - d.loc[has_coords, "hit_y"]) * 2.4384
        else:
            d.loc[has_coords, "x_ft"] = d.loc[has_coords, "hit_x"]
            d.loc[has_coords, "y_ft"] = d.loc[has_coords, "hit_y"]

    if PULL_SIGN_FLIP:
        d["x_ft"] = -d["x_ft"]

    d["spray_angle_deg"] = np.degrees(np.arctan2(d["x_ft"], d["y_ft"].clip(lower=1)))
    has_hand_col = "batter_hand" in d.columns

    def side(row):
        if pd.isna(row["spray_angle_deg"]):
            return None
        angle = row["spray_angle_deg"]
        row_hand = row.get("batter_hand") if has_hand_col and pd.notna(row.get("batter_hand")) else batter_hand
        hand = str(row_hand).upper()
        if hand.startswith("L"):
            angle = -angle
        if angle < -15:
            return "Pull"
        if angle > 15:
            return "Opposite"
        return "Center"

    d["field_side"] = d.apply(side, axis=1)
    d["bb_type"] = d["trajectory"].apply(_bb_type)
    return d


def compute_batted_ball_profile(enriched_df: pd.DataFrame) -> dict:
    bip = enriched_df[enriched_df["in_play"] == True]  # noqa: E712
    n = len(bip)
    if n == 0:
        return {k: np.nan for k in ["gb_pct", "fb_pct", "ld_pct", "pu_pct",
                                     "pull_pct", "cent_pct", "oppo_pct"]}
    return {
        "gb_pct": _safe_div((bip["bb_type"] == "ground_ball").sum(), n),
        "fb_pct": _safe_div((bip["bb_type"] == "fly_ball").sum(), n),
        "ld_pct": _safe_div((bip["bb_type"] == "line_drive").sum(), n),
        "pu_pct": _safe_div((bip["bb_type"] == "popup").sum(), n),
        "pull_pct": _safe_div((bip["field_side"] == "Pull").sum(), n),
        "cent_pct": _safe_div((bip["field_side"] == "Center").sum(), n),
        "oppo_pct": _safe_div((bip["field_side"] == "Opposite").sum(), n),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pitch-type breakdown table
# ─────────────────────────────────────────────────────────────────────────────

def compute_pitch_type_table(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "pitch_description" not in df.columns:
        return pd.DataFrame()

    d = df.copy()
    d["is_swing_b"] = _bool(d["is_swing"])
    d["is_whiff_b"] = _bool(d["is_whiff"])
    total_pitches = len(d)
    pa_df = d[d["event_type"].notna()]
    pa_df = pa_df[~is_non_pa_event(pa_df["event_type"])]

    rows = []
    for pdesc, grp in d.groupby("pitch_description"):
        n = len(grp)
        n_sw = grp["is_swing_b"].sum()
        n_wh = grp["is_whiff_b"].sum()

        grp_pa = pa_df[pa_df["pitch_description"] == pdesc]
        n_pa_p = len(grp_pa)
        ab_grp = grp_pa[~grp_pa["event_type"].isin(NON_AB_EVENTS)]
        n_ab_p = len(ab_grp)

        row = {
            "pitch_type": shorten_pitch(pdesc),
            "color": PITCH_COLORS.get(str(pdesc), "#AAAAAA"),
            "usage_pct": _safe_div(n, total_pitches) * 100,
            "n_pitches": n,
            "swing_pct": _safe_div(n_sw, n) * 100,
            "whiff_pct": _safe_div(n_wh, n_sw) * 100 if n_sw else 0,
            "pa": n_pa_p,
            "ab": n_ab_p,
        }
        if n_ab_p > 0:
            n_hits_p = ab_grp["event_type"].isin(HIT_EVENTS).sum()
            n_bb_p = grp_pa["event_type"].isin(WALK_EVENTS).sum()
            n_hbp_p = (grp_pa["event_type"] == "hit_by_pitch").sum()
            n_sf_p = grp_pa["event_type"].isin(["sac_fly", "sac_fly_double_play"]).sum()
            n_k_p = grp_pa["event_type"].isin(["strikeout", "strikeout_double_play"]).sum()
            tb_p = (
                (ab_grp["event_type"] == "single").sum()
                + 2 * (ab_grp["event_type"] == "double").sum()
                + 3 * (ab_grp["event_type"] == "triple").sum()
                + 4 * (ab_grp["event_type"] == "home_run").sum()
            )
            ba_p = _safe_div(n_hits_p, n_ab_p)
            obp_p = _safe_div(n_hits_p + n_bb_p + n_hbp_p, n_ab_p + n_bb_p + n_hbp_p + n_sf_p)
            slg_p = _safe_div(tb_p, n_ab_p)
            row.update({
                "ba": ba_p, "obp": obp_p, "slg": slg_p,
                "ops": (obp_p or 0) + (slg_p or 0),
                "k_pct": _safe_div(n_k_p, n_pa_p) * 100,
                "bb_pct": _safe_div(n_bb_p, n_pa_p) * 100,
            })
        else:
            row.update({"ba": np.nan, "obp": np.nan, "slg": np.nan, "ops": np.nan,
                        "k_pct": np.nan, "bb_pct": np.nan})
        rows.append(row)

    result = pd.DataFrame(rows).sort_values("n_pitches", ascending=False, ignore_index=True)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Count-based swing rate matrix
# ─────────────────────────────────────────────────────────────────────────────

def compute_count_matrix(df: pd.DataFrame):
    """Returns (swing_rate, contact_rate, n_pitches), each a 3x4 array
    indexed [strikes, balls]. contact_rate is (swings - whiffs) / swings for
    that count — same 'Contact%' definition used elsewhere in the app (a
    caught foul tip counts as a whiff here, matching compute_contact_profile
    and compute_plate_discipline). See compute_contact_rate_matrix_by_zone()
    for the version that further splits this by in-zone vs. out-of-zone."""
    swing = np.full((3, 4), np.nan)
    contact = np.full((3, 4), np.nan)
    counts = np.zeros((3, 4), dtype=int)
    if df is None or df.empty:
        return swing, contact, counts

    d = df.copy()
    d["is_swing_b"] = _bool(d["is_swing"])
    d["is_whiff_b"] = _bool(d["is_whiff"])
    for b in range(4):
        for s in range(3):
            cell = d[(d["balls"] == b) & (d["strikes"] == s)]
            n = len(cell)
            counts[s, b] = n
            if n > 0:
                n_swings = cell["is_swing_b"].sum()
                swing[s, b] = n_swings / n
                if n_swings > 0:
                    n_whiffs = cell["is_whiff_b"].sum()
                    contact[s, b] = (n_swings - n_whiffs) / n_swings
    return swing, contact, counts


def compute_contact_rate_matrix_by_zone(df: pd.DataFrame):
    """Contact rate by ball-strike count, split into two separate 3x4 grids
    (indexed [strikes, balls]) — one for swings at pitches in the zone, one
    for swings at pitches out of the zone (chase). Combines the "by count"
    and "in zone vs out of zone" views: e.g. does this hitter's contact rate
    on pitches IN the zone change with two strikes, versus his contact rate
    on pitches he's chasing out of the zone.

    Returns (in_zone_contact, in_zone_swings, out_zone_contact, out_zone_swings).
    """
    in_zone_contact = np.full((3, 4), np.nan)
    in_zone_swings = np.zeros((3, 4), dtype=int)
    out_zone_contact = np.full((3, 4), np.nan)
    out_zone_swings = np.zeros((3, 4), dtype=int)
    if df is None or df.empty:
        return in_zone_contact, in_zone_swings, out_zone_contact, out_zone_swings

    d = df.copy()
    d["is_swing_b"] = _bool(d["is_swing"])
    d["is_whiff_b"] = _bool(d["is_whiff"])
    d["in_zone_b"] = _in_zone_mask(d)

    for b in range(4):
        for s in range(3):
            base = d[(d["balls"] == b) & (d["strikes"] == s) & d["is_swing_b"]]
            iz = base[base["in_zone_b"]]
            oz = base[~base["in_zone_b"]]

            n_iz = len(iz)
            in_zone_swings[s, b] = n_iz
            if n_iz > 0:
                in_zone_contact[s, b] = (n_iz - iz["is_whiff_b"].sum()) / n_iz

            n_oz = len(oz)
            out_zone_swings[s, b] = n_oz
            if n_oz > 0:
                out_zone_contact[s, b] = (n_oz - oz["is_whiff_b"].sum()) / n_oz

    return in_zone_contact, in_zone_swings, out_zone_contact, out_zone_swings


def compute_count_cell_detail(df: pd.DataFrame, zone_filter: str = None) -> np.ndarray:
    """Builds a (3,4) array of hover-text strings (indexed [strikes, balls])
    describing what actually happened on the swings in each count cell —
    how many were whiffs, fouls, and for balls in play, the breakdown of
    singles/doubles/triples/HR/outs. This is what powers the hover tooltip
    on the contact-rate-by-count heatmaps, so a cell showing '100% contact'
    can be inspected to see whether that was all weak fouls or actual damage.

    zone_filter: None (all swings), "in" (in-zone only), "out" (out-of-zone
    chase swings only).
    """
    detail = np.empty((3, 4), dtype=object)
    detail[:] = "No swings"
    if df is None or df.empty:
        return detail

    d = df.copy()
    d["is_swing_b"] = _bool(d["is_swing"])
    d["is_whiff_b"] = _bool(d["is_whiff"])
    if zone_filter in ("in", "out"):
        in_zone = _in_zone_mask(d)
        d = d[in_zone] if zone_filter == "in" else d[~in_zone]

    for b in range(4):
        for s in range(3):
            cell = d[(d["balls"] == b) & (d["strikes"] == s) & d["is_swing_b"]]
            n = len(cell)
            if n == 0:
                continue
            n_whiff = int(cell["is_whiff_b"].sum())
            in_play = cell[cell["in_play"] == True]  # noqa: E712
            n_in_play = len(in_play)
            n_foul = n - n_whiff - n_in_play

            lines = [f"<b>{b}-{s} count — {n} swings</b>"]
            lines.append(f"Whiffs: {n_whiff}")
            lines.append(f"Fouls: {n_foul}")
            if n_in_play > 0:
                singles = int((in_play["event_type"] == "single").sum())
                doubles = int((in_play["event_type"] == "double").sum())
                triples = int((in_play["event_type"] == "triple").sum())
                hr = int((in_play["event_type"] == "home_run").sum())
                outs = n_in_play - singles - doubles - triples - hr
                parts = []
                if hr:
                    parts.append(f"{hr} HR")
                if triples:
                    parts.append(f"{triples} 3B")
                if doubles:
                    parts.append(f"{doubles} 2B")
                if singles:
                    parts.append(f"{singles} 1B")
                if outs:
                    parts.append(f"{outs} out{'s' if outs != 1 else ''}")
                lines.append(f"In Play: {n_in_play} (" + ", ".join(parts) + ")")
            else:
                lines.append("In Play: 0")
            detail[s, b] = "<br>".join(lines)
    return detail


def compute_contact_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Swing outcomes — Whiff / Foul Ball / In Play — split by whether the
    pitch was in the strike zone or not. The percentage for each outcome is
    out of swings taken in that zone group (so this reads as "of the swings
    they took [in/out of] the zone, what fraction ended in each outcome").

    Whiff here includes caught foul tips, same as everywhere else in the
    app (is_whiff already encodes that — a caught foul tip behaves like a
    swing-and-miss for a batter's approach, not like real contact). A
    regular foul ball that isn't a caught tip still counts as contact.
    """
    if df is None or df.empty or "is_swing" not in df.columns:
        return pd.DataFrame()

    d = df.copy()
    d["is_swing_b"] = _bool(d["is_swing"])
    d["is_whiff_b"] = _bool(d["is_whiff"])
    swings = d[d["is_swing_b"]].copy()
    if swings.empty:
        return pd.DataFrame()

    in_zone = _in_zone_mask(swings)
    swings["zone_group"] = np.where(in_zone, "In Zone", "Out of Zone")

    def classify(row):
        if row["is_whiff_b"]:
            return "Whiff"
        if row.get("in_play") is True:
            return "In Play"
        return "Foul Ball"

    swings["outcome"] = swings.apply(classify, axis=1)

    rows = []
    for zg in ["In Zone", "Out of Zone"]:
        grp = swings[swings["zone_group"] == zg]
        n = len(grp)
        if n == 0:
            continue
        vc = grp["outcome"].value_counts()
        for outcome in ["Whiff", "Foul Ball", "In Play"]:
            rows.append({
                "zone_group": zg, "outcome": outcome,
                "n": int(vc.get(outcome, 0)),
                "pct": float(vc.get(outcome, 0)) / n * 100,
            })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Rolling trend
# ─────────────────────────────────────────────────────────────────────────────

def compute_team_run_trend(df: pd.DataFrame, team_id: int, schedule_df: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """Rolling runs-scored/runs-allowed per game for a team, built from the
    per-pitch feed's running score fields plus the schedule's home/away
    lookup (to know which side of home_score/away_score is this team's).
    Defensive by design: returns an empty frame rather than raising if the
    score columns aren't present or nothing matches, since this is a bonus
    chart, not core functionality."""
    required = {"game_id", "game_date", "home_score", "away_score"}
    if df is None or df.empty or not required.issubset(df.columns):
        return pd.DataFrame()
    if schedule_df is None or schedule_df.empty:
        return pd.DataFrame()

    per_game = df.groupby("game_id").agg(
        game_date=("game_date", "first"),
        home_score=("home_score", "max"),
        away_score=("away_score", "max"),
    ).reset_index()
    merged = per_game.merge(schedule_df[["game_id", "home_id", "away_id"]], on="game_id", how="left")
    merged = merged.dropna(subset=["home_id"])
    if merged.empty:
        return pd.DataFrame()

    merged["team_runs"] = np.where(merged["home_id"] == team_id, merged["home_score"], merged["away_score"])
    merged["opp_runs"] = np.where(merged["home_id"] == team_id, merged["away_score"], merged["home_score"])
    merged["game_date"] = pd.to_datetime(merged["game_date"])
    merged.sort_values("game_date", inplace=True)
    merged["roll_runs_scored"] = merged["team_runs"].rolling(window, min_periods=3).mean()
    merged["roll_runs_allowed"] = merged["opp_runs"].rolling(window, min_periods=3).mean()

    return merged[["game_date", "team_runs", "opp_runs", "roll_runs_scored", "roll_runs_allowed"]].dropna(
        how="all", subset=["roll_runs_scored"]
    )


def filter_by_period(df: pd.DataFrame, period: str, last_n_games: int = None,
                      start_date=None, end_date=None, restrict_to_game_ids=None) -> pd.DataFrame:
    """Filters a pitch-level dataframe down to a portion of the season.

    period: "full" (no filtering), "last_n" (the most recent last_n_games
    distinct games by date), or "custom" (game_date between start_date and
    end_date, inclusive).

    "Last N games" is computed from the games actually present in df, not
    from a separate schedule lookup — a player's own game log is exactly
    the right source of truth for "their last N games", and this needs no
    additional network call since df is already loaded.

    restrict_to_game_ids (optional, only affects "last_n"): limits which
    games count toward "last N" to this set — used for the pitcher page's
    "Last N Starts" mode, where relief appearances shouldn't count toward
    or appear in a starts-only window. "full" and "custom" are unaffected,
    since a date range or the whole season should include everything that
    happened in it regardless of role.
    """
    if df is None or df.empty or period == "full":
        return df

    dates = pd.to_datetime(df["game_date"])

    if period == "last_n" and last_n_games:
        candidate = df if restrict_to_game_ids is None else df[df["game_id"].isin(restrict_to_game_ids)]
        if candidate.empty:
            return candidate
        candidate_dates = pd.to_datetime(candidate["game_date"])
        games = pd.DataFrame({"game_id": candidate["game_id"].values, "game_date": candidate_dates.values})
        games = games.drop_duplicates().sort_values("game_date")
        keep_ids = set(games["game_id"].tail(int(last_n_games)))
        return df[df["game_id"].isin(keep_ids)]

    if period == "custom" and start_date is not None and end_date is not None:
        mask = (dates >= pd.Timestamp(start_date)) & (dates <= pd.Timestamp(end_date))
        return df[mask]

    return df


def compute_rolling_trend(df: pd.DataFrame, window: int = 25) -> pd.DataFrame:
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
    pa_df["roll_avg"] = pa_df["roll_hits"] / pa_df["roll_ab"]
    pa_df["roll_k_pct"] = pa_df["is_k"].rolling(window, min_periods=5).mean() * 100
    pa_df["roll_bb_pct"] = pa_df["is_bb"].rolling(window, min_periods=5).mean() * 100

    return pa_df[["game_date", "roll_avg", "roll_k_pct", "roll_bb_pct"]].dropna(how="all", subset=["roll_avg"])


# Every stat selectable in the Trends tab's multi-select. Order here is the
# order shown in the dropdown. Grouped loosely by what they're computed from
# (PA outcomes, pitch-level swing decisions, batted-ball quality) even
# though they're all rolled over the same "last N plate appearances" window
# for a consistent, comparable x-axis — see compute_multi_rolling_trend.
TREND_STAT_OPTIONS = [
    "AVG", "OBP", "SLG", "OPS", "ISO", "BABIP",
    "K%", "BB%",
    "Swing%", "Zone%", "Z-Swing%", "Chase%", "Contact%", "CSW%",
    "Whiff%", "Whiff% (in zone)", "Whiff% (out of zone)",
    "Hard-Hit%", "Sweet-Spot%", "Avg Exit Velo",
]

# How each stat's rolling VALUE should be displayed — "rate3" for things
# conventionally shown as a leading-dot-dropped decimal (.274 not 27.4%),
# "pct" for a percentage, "num1" for a raw one-decimal number (mph).
TREND_STAT_FORMAT = {
    "AVG": "rate3", "OBP": "rate3", "SLG": "rate3", "OPS": "rate3", "ISO": "rate3", "BABIP": "rate3",
    "K%": "pct", "BB%": "pct",
    "Swing%": "pct", "Zone%": "pct", "Z-Swing%": "pct", "Chase%": "pct", "Contact%": "pct", "CSW%": "pct",
    "Whiff%": "pct", "Whiff% (in zone)": "pct", "Whiff% (out of zone)": "pct",
    "Hard-Hit%": "pct", "Sweet-Spot%": "pct",
    "Avg Exit Velo": "num1",
}


def compute_multi_rolling_trend(df: pd.DataFrame, window: int, stat_names: list) -> pd.DataFrame:
    """Rolling trend for any combination of TREND_STAT_OPTIONS, all computed
    over the same "last N plate appearances" window so they're directly
    comparable on one x-axis and one game_date column — regardless of
    whether the underlying stat is fundamentally a per-PA outcome (AVG), a
    per-pitch swing-decision rate (Whiff%, Chase%), or a per-batted-ball
    quality rate (Hard-Hit%, Avg Exit Velo).

    Works by assigning every pitch a sequential plate-appearance index
    (pa_seq, chronological), aggregating the relevant counts (swings,
    whiffs, in-zone pitches, batted balls, etc) once per PA, then applying
    a single rolling sum over pa_seq for each requested stat's numerator
    and denominator. A pitch-level or batted-ball-level stat can come back
    NaN for early points in a short window if that window's PAs happened
    to include few/no swings or few/no batted balls — that's a real
    reflection of small-sample sparseness, not a bug.
    """
    if df is None or df.empty or not stat_names or "ab_number" not in df.columns:
        return pd.DataFrame()

    d = df.copy()
    d["game_date"] = pd.to_datetime(d["game_date"])
    d.sort_values(["game_date", "ab_number"], inplace=True, kind="stable")

    pa_keys = d[["game_id", "ab_number"]].drop_duplicates().reset_index(drop=True)
    pa_keys["pa_seq"] = pa_keys.index
    d = d.merge(pa_keys, on=["game_id", "ab_number"], how="left")

    d["is_swing_b"] = _bool(d["is_swing"])
    d["is_whiff_b"] = _bool(d["is_whiff"])
    d["in_zone_b"] = _in_zone_mask(d)
    d["is_strike_b"] = _bool(d["is_strike"]) if "is_strike" in d.columns else False

    d["iz_swing"] = d["is_swing_b"] & d["in_zone_b"]
    d["iz_whiff"] = d["is_whiff_b"] & d["in_zone_b"]
    d["oz_pitch"] = ~d["in_zone_b"]
    d["oz_swing"] = d["is_swing_b"] & ~d["in_zone_b"]
    d["oz_whiff"] = d["is_whiff_b"] & ~d["in_zone_b"]
    d["contact"] = d["is_swing_b"] & ~d["is_whiff_b"]

    has_launch_data = "launch_speed" in d.columns and "launch_angle" in d.columns
    if has_launch_data:
        is_bip = _bool(d["in_play"]) if "in_play" in d.columns else pd.Series(False, index=d.index)
        d["is_bip_ev"] = is_bip & d["launch_speed"].notna()
        d["is_hard_hit"] = d["is_bip_ev"] & (d["launch_speed"] >= 95)
        d["is_sweet_spot"] = d["is_bip_ev"] & d["launch_angle"].between(8, 32)
        d["ev_value"] = np.where(d["is_bip_ev"], d["launch_speed"], 0.0)
    else:
        d["is_bip_ev"] = False
        d["is_hard_hit"] = False
        d["is_sweet_spot"] = False
        d["ev_value"] = 0.0

    pa_df = d[d["event_type"].notna()].copy()
    pa_df = pa_df[~is_non_pa_event(pa_df["event_type"])]
    pa_df["is_hit"] = pa_df["event_type"].isin(HIT_EVENTS)
    pa_df["is_ab"] = ~pa_df["event_type"].isin(NON_AB_EVENTS)
    pa_df["is_bb"] = pa_df["event_type"].isin(WALK_EVENTS)
    pa_df["is_k"] = pa_df["event_type"].isin(["strikeout", "strikeout_double_play"])
    pa_df["is_hbp"] = pa_df["event_type"] == "hit_by_pitch"
    pa_df["is_sf"] = pa_df["event_type"].isin(["sac_fly", "sac_fly_double_play"])
    pa_df["tb"] = (
        pa_df["event_type"].eq("single").astype(int)
        + 2 * pa_df["event_type"].eq("double").astype(int)
        + 3 * pa_df["event_type"].eq("triple").astype(int)
        + 4 * pa_df["event_type"].eq("home_run").astype(int)
    )
    pa_outcomes = pa_df.set_index("pa_seq")[["is_hit", "is_ab", "is_bb", "is_k", "is_hbp", "is_sf", "tb"]]

    per_pa = d.groupby("pa_seq").agg(
        game_date=("game_date", "first"),
        n_pitches=("pa_seq", "size"),
        n_swings=("is_swing_b", "sum"),
        n_whiffs=("is_whiff_b", "sum"),
        n_iz_pitches=("in_zone_b", "sum"),
        n_iz_swings=("iz_swing", "sum"),
        n_iz_whiffs=("iz_whiff", "sum"),
        n_oz_pitches=("oz_pitch", "sum"),
        n_oz_swings=("oz_swing", "sum"),
        n_oz_whiffs=("oz_whiff", "sum"),
        n_contacts=("contact", "sum"),
        n_csw=("is_strike_b", "sum"),
        n_bip_ev=("is_bip_ev", "sum"),
        n_hard_hit=("is_hard_hit", "sum"),
        n_sweet_spot=("is_sweet_spot", "sum"),
        sum_ev=("ev_value", "sum"),
    )
    per_pa = per_pa.join(pa_outcomes, how="left")
    for c in ["is_hit", "is_ab", "is_bb", "is_k", "is_hbp", "is_sf", "tb"]:
        per_pa[c] = per_pa[c].fillna(0)
    per_pa["is_pa"] = 1

    min_p = max(3, window // 4)

    def roll(col):
        return per_pa[col].rolling(window, min_periods=min_p).sum()

    r_ab, r_hit, r_pa = roll("is_ab"), roll("is_hit"), roll("is_pa")
    r_bb, r_k, r_hbp, r_sf, r_tb = roll("is_bb"), roll("is_k"), roll("is_hbp"), roll("is_sf"), roll("tb")
    r_swings, r_whiffs = roll("n_swings"), roll("n_whiffs")
    r_iz_p, r_iz_sw, r_iz_wh = roll("n_iz_pitches"), roll("n_iz_swings"), roll("n_iz_whiffs")
    r_oz_p, r_oz_sw, r_oz_wh = roll("n_oz_pitches"), roll("n_oz_swings"), roll("n_oz_whiffs")
    r_contacts, r_csw, r_pitches = roll("n_contacts"), roll("n_csw"), roll("n_pitches")
    r_bip, r_hh, r_ss, r_ev = roll("n_bip_ev"), roll("n_hard_hit"), roll("n_sweet_spot"), roll("sum_ev")

    avg = r_hit / r_ab
    obp = (r_hit + r_bb + r_hbp) / (r_ab + r_bb + r_hbp + r_sf)
    slg = r_tb / r_ab

    result = pd.DataFrame({"game_date": per_pa["game_date"].values})
    for name in stat_names:
        if name == "AVG":
            result[name] = avg.values
        elif name == "OBP":
            result[name] = obp.values
        elif name == "SLG":
            result[name] = slg.values
        elif name == "OPS":
            result[name] = (obp + slg).values
        elif name == "ISO":
            result[name] = (slg - avg).values
        elif name == "BABIP":
            # (H - HR) / (AB - K - HR + SF); HR not separately rolled above,
            # so approximate via tb==4 count per PA window.
            hr_flag = (pa_df.set_index("pa_seq")["event_type"] == "home_run")
            hr_flag = hr_flag.reindex(per_pa.index, fill_value=False).astype(int)
            r_hr = hr_flag.rolling(window, min_periods=min_p).sum()
            result[name] = ((r_hit - r_hr) / (r_ab - r_k - r_hr + r_sf)).values
        elif name == "K%":
            result[name] = (r_k / r_pa).values
        elif name == "BB%":
            result[name] = (r_bb / r_pa).values
        elif name == "Swing%":
            result[name] = (r_swings / r_pitches).values
        elif name == "Zone%":
            result[name] = (r_iz_p / r_pitches).values
        elif name == "Z-Swing%":
            result[name] = (r_iz_sw / r_iz_p).values
        elif name == "Chase%":
            result[name] = (r_oz_sw / r_oz_p).values
        elif name == "Contact%":
            result[name] = (r_contacts / r_swings).values
        elif name == "CSW%":
            result[name] = (r_csw / r_pitches).values
        elif name == "Whiff%":
            result[name] = (r_whiffs / r_swings).values
        elif name == "Whiff% (in zone)":
            result[name] = (r_iz_wh / r_iz_sw).values
        elif name == "Whiff% (out of zone)":
            result[name] = (r_oz_wh / r_oz_sw).values
        elif name == "Hard-Hit%":
            result[name] = (r_hh / r_bip).values
        elif name == "Sweet-Spot%":
            result[name] = (r_ss / r_bip).values
        elif name == "Avg Exit Velo":
            result[name] = (r_ev / r_bip).values

    return result.dropna(how="all", subset=[c for c in stat_names if c in result.columns])


# ─────────────────────────────────────────────────────────────────────────────
# Splits
# ─────────────────────────────────────────────────────────────────────────────

def compute_splits(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {}
    splits = {}
    if "pitcher_hand" in df.columns:
        for hand, label in [("L", "vs LHP"), ("R", "vs RHP")]:
            splits[label] = compute_slash_line(df[df["pitcher_hand"] == hand])
    if "is_home" in df.columns:
        splits["Home"] = compute_slash_line(df[df["is_home"] == True])  # noqa: E712
        splits["Away"] = compute_slash_line(df[df["is_home"] == False])  # noqa: E712
    return splits


# ─────────────────────────────────────────────────────────────────────────────
# Percentile table
# ─────────────────────────────────────────────────────────────────────────────

PERCENTILE_METRICS = [
    # (label, player-value key or callable, standard-pool column, savant-pool column, higher_is_better)
    ("AVG", "ba", "avg", "avg", True),
    ("OBP", "obp", "obp", "obp", True),
    ("SLG", "slg", "slg", "slg", True),
    ("OPS", "ops", "ops", "ops", True),
    ("K%", "k_pct", "k_pct", "k_pct_savant", False),
    ("BB%", "bb_pct", "bb_pct", "bb_pct_savant", True),
    ("Hard-Hit%", "hard_hit_pct", None, "hard_hit_pct", True),
    ("Avg Exit Velo", "avg_ev", None, "avg_ev", True),
    ("Chase%", "chase_pct", None, "chase_pct", False),
    ("Whiff%", "whiff_pct", None, "whiff_pct", False),
    ("Sweet-Spot%", "sweet_spot_pct", None, "sweet_spot_pct", True),
]


def build_percentile_table(
    player_stats: dict,
    standard_pool: pd.DataFrame,
    savant_pool: pd.DataFrame,
    is_mlb: bool,
) -> pd.DataFrame:
    from data_layer import percentile_rank  # local import avoids a cycle at module load

    rows = []
    for label, key, std_col, savant_col, higher_is_better in PERCENTILE_METRICS:
        value = player_stats.get(key)
        pct = None
        source = None

        if std_col and standard_pool is not None and not standard_pool.empty and std_col in standard_pool.columns:
            qualified_pool = standard_pool[standard_pool["qualified"]]
            pct = percentile_rank(value, qualified_pool[std_col])
            source = "league (qualified)"
        elif is_mlb and savant_col and savant_pool is not None and not savant_pool.empty and savant_col in savant_pool.columns:
            pct = percentile_rank(value, savant_pool[savant_col])
            source = "MLB Statcast (qualified)"

        if pct is not None and not higher_is_better:
            pct = 100 - pct

        rows.append({
            "metric": label, "value": value, "percentile": pct, "source": source,
        })
    return pd.DataFrame(rows)
