import numpy as np
import pandas as pd

import data_layer

fake_teams = pd.DataFrame([
    {"team_id": 136, "name": "Seattle Mariners", "abbreviation": "SEA", "league_name": "American League"},
    {"team_id": 147, "name": "New York Yankees", "abbreviation": "NYY", "league_name": "American League"},
])

fake_team_hitting = pd.DataFrame([
    {"team_id": 136, "team": "Seattle Mariners", "games_played": 120, "plate_appearances": 4600,
     "at_bats": 4100, "runs": 560, "hits": 1020, "home_runs": 165, "walks": 400, "strikeouts": 1050,
     "avg": 0.249, "obp": 0.320, "slg": 0.420, "ops": 0.740,
     "k_pct": 0.228, "bb_pct": 0.087, "runs_per_game": 4.67},
    {"team_id": 147, "team": "New York Yankees", "games_played": 120, "plate_appearances": 4700,
     "at_bats": 4150, "runs": 620, "hits": 1080, "home_runs": 190, "walks": 450, "strikeouts": 980,
     "avg": 0.260, "obp": 0.335, "slg": 0.450, "ops": 0.785,
     "k_pct": 0.209, "bb_pct": 0.096, "runs_per_game": 5.17},
])

fake_team_pitching = pd.DataFrame([
    {"team_id": 136, "team": "Seattle Mariners", "games_played": 120, "innings_pitched": 1080.0,
     "batters_faced": 4500, "runs_allowed": 480, "earned_runs": 440, "hits_allowed": 950,
     "walks": 380, "strikeouts": 1100, "home_runs": 120, "saves": 30, "wins": 65, "losses": 55,
     "era": 3.67, "whip": 1.23, "k_pct": 0.244, "bb_pct": 0.084, "runs_allowed_per_game": 4.0},
])

fake_hitters_roster = pd.DataFrame([
    {"player_id": 1, "name": "Batter A", "team": "Seattle Mariners", "plate_appearances": 550, "at_bats": 500,
     "avg": 0.280, "obp": 0.360, "slg": 0.480, "ops": 0.840, "home_runs": 28,
     "k_pct": 0.20, "bb_pct": 0.10, "qualified": True},
    {"player_id": 2, "name": "Batter B", "team": "Seattle Mariners", "plate_appearances": 500, "at_bats": 450,
     "avg": 0.240, "obp": 0.300, "slg": 0.400, "ops": 0.700, "home_runs": 15,
     "k_pct": 0.25, "bb_pct": 0.07, "qualified": True},
])

fake_pitchers_roster = pd.DataFrame([
    {"player_id": 10, "name": "Pitcher A", "team": "Seattle Mariners", "innings_pitched": 180.0,
     "era": 3.10, "whip": 1.05, "k_pct": 0.28, "bb_pct": 0.06, "wins": 14, "losses": 6, "saves": 0,
     "qualified": True, "relief_pool": True},
])

fake_savant_batting = pd.DataFrame({
    "player_id": [1, 2],
    "name": ["Batter A", "Batter B"],
    "hard_hit_pct": [0.45, 0.35],
    "avg_ev": [91.0, 88.0],
    "chase_pct": [0.25, 0.30],
    "whiff_pct": [0.22, 0.28],
    "sweet_spot_pct": [0.35, 0.30],
})
fake_savant_pitching = pd.DataFrame({
    "player_id": [10],
    "name": ["Pitcher A"],
    "whiff_pct": [0.28],
    "chase_pct": [0.30],
    "hard_hit_pct_against": [0.32],
    "avg_ev_against": [88.0],
})

data_layer.get_team_list = lambda season, sport_id, force_refresh=False: fake_teams.copy()
data_layer.get_team_hitting_leaderboard = lambda season, sport_id, force_refresh=False, start_date=None, end_date=None: fake_team_hitting.copy()
data_layer.get_team_pitching_leaderboard = lambda season, sport_id, force_refresh=False, start_date=None, end_date=None: fake_team_pitching.copy()
data_layer.get_standard_leaderboard = lambda season, sport_id, force_refresh=False, start_date=None, end_date=None: fake_hitters_roster.copy()
data_layer.get_pitching_standard_leaderboard = lambda season, sport_id, force_refresh=False, start_date=None, end_date=None: fake_pitchers_roster.copy()
data_layer.get_savant_percentile_pool = lambda season, force_refresh=False: fake_savant_batting.copy()
data_layer.get_pitching_savant_percentile_pool = lambda season, force_refresh=False: fake_savant_pitching.copy()

# ── Synthetic team-wide pitch log for the deep-dive tabs ─────────────────────
import numpy as _np
_np.random.seed(3)
_pitch_types = ["Four-Seam Fastball", "Slider", "Changeup", "Curveball"]
_events = [None] * 4 + ["single", "double", "home_run", "walk", "strikeout", "field_out"]
_rows = []
_dates = pd.date_range("2026-03-28", periods=60, freq="D")
for i in range(500):
    is_last = _np.random.random() < 0.25
    is_mariners_batting = i % 2 == 0
    in_play = is_last and _np.random.random() < 0.3
    _rows.append({
        "game_id": 900000 + (i // 20),
        "game_date": str(_dates[(i // 20) % len(_dates)].date()),
        "batter_team_id": 136 if is_mariners_batting else 133,
        "pitcher_team_id": 133 if is_mariners_batting else 136,
        "batter_hand": _np.random.choice(["L", "R"]),
        "pitcher_hand": "R",
        "ab_number": i // 4,
        "pitch_description": _np.random.choice(_pitch_types),
        "is_swing": True if _np.random.random() < 0.45 else None,
        "is_whiff": True if _np.random.random() < 0.12 else None,
        "is_strike": _np.random.random() < 0.4,
        "in_play": in_play,
        "balls": _np.random.randint(0, 4),
        "strikes": _np.random.randint(0, 3),
        "px": _np.random.uniform(-2, 2),
        "pz": _np.random.uniform(0.8, 4.5),
        "sz_top": 3.4, "sz_bot": 1.5,
        "zone": _np.random.randint(1, 15),
        "launch_speed": _np.random.uniform(60, 108) if in_play else None,
        "launch_angle": _np.random.uniform(-30, 50) if in_play else None,
        "trajectory": _np.random.choice(["fly_ball", "ground_ball", "line_drive", "popup"]) if in_play else None,
        "hit_x": _np.random.uniform(60, 200) if in_play else None,
        "hit_y": _np.random.uniform(60, 200) if in_play else None,
        "event_type": _np.random.choice(_events) if is_last else None,
        "home_score": min(i // 30, 5),
        "away_score": min(i // 40, 4),
        "home_id": 136,
        "away_id": 133,
    })
fake_team_pitch_log = pd.DataFrame(_rows)
fake_schedule_lookup = fake_team_pitch_log[["game_id", "game_date", "home_id", "away_id"]].drop_duplicates()

data_layer.get_team_pitch_log = lambda **kwargs: fake_team_pitch_log.copy()
data_layer.get_schedule_lookup = lambda season, sport_id, force_refresh=False: fake_schedule_lookup.copy()

from streamlit.testing.v1 import AppTest  # noqa: E402

at = AppTest.from_file("views/team_dashboard.py", default_timeout=60)
at.run()
assert not at.exception, f"Exception on initial run: {list(at.exception)}"

at.selectbox(key="t_team").select("Seattle Mariners")
at.run()
assert not at.exception, f"Exception after selecting team: {list(at.exception)}"

load_buttons = [b for b in at.button if b.label == "Load team"]
assert load_buttons, "Load team button not found"
load_buttons[0].click()
at.run()

exceptions = list(at.exception)
if exceptions:
    for e in exceptions:
        print("EXCEPTION:", e)
    raise SystemExit(1)

print("Num metrics rendered:", len(at.get("metric")))
print("Num plotly charts:", len(at.get("plotly_chart") if at.get("plotly_chart") else []))
print("Num dataframes:", len(at.get("dataframe") if at.get("dataframe") else []))
print("Warnings:", [w.value[:200] for w in at.warning])
print("\nTEAM HAPPY PATH TEST PASSED (bulk stats) — full team view rendered with no exceptions.")

# ── Now drive the pitch-level deep dive load ─────────────────────────────────
dd_load_buttons = [b for b in at.button if b.label == "Load pitch-level splits"]
assert dd_load_buttons, "Load pitch-level splits button not found"
dd_load_buttons[0].click()
at.run()

exceptions = list(at.exception)
if exceptions:
    for e in exceptions:
        print("EXCEPTION (deep dive):", e)
    raise SystemExit(1)

print("Num tabs after deep dive load:", len(at.tabs))
print("Num plotly charts after deep dive load:", len(at.get("plotly_chart") if at.get("plotly_chart") else []))
print("Num metrics after deep dive load:", len(at.get("metric")))
print("Warnings after deep dive:", [w.value[:200] for w in at.warning])
print("\nTEAM DEEP DIVE TEST PASSED — pitch-type/discipline/contact/trend tabs rendered with no exceptions.")
