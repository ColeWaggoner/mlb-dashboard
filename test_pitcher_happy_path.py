import numpy as np
import pandas as pd

import data_layer
from test_pitching_smoke import df as synthetic_pitcher_df

fake_universe = pd.DataFrame([
    {"player_id": 987654, "name": "Test Pitcher", "position": "P", "team": "Seattle Mariners",
     "sport_id": 1, "level": "MLB", "display_name": "Test Pitcher  —  MLB"},
])

fake_standard_pool = pd.DataFrame({
    "era": np.random.uniform(2.5, 5.5, 150),
    "whip": np.random.uniform(0.9, 1.5, 150),
    "k_pct": np.random.uniform(0.15, 0.35, 150),
    "bb_pct": np.random.uniform(0.04, 0.12, 150),
    "k_bb_pct": np.random.uniform(0.05, 0.25, 150),
    "hr_per_9": np.random.uniform(0.5, 1.8, 150),
    "fip": np.random.uniform(2.8, 5.0, 150),
    "qualified": np.random.choice([True, False], 150, p=[0.3, 0.7]),
    "relief_pool": True,
})
fake_savant_pool = pd.DataFrame({
    "whiff_pct": np.random.uniform(0.2, 0.35, 150),
    "chase_pct": np.random.uniform(0.25, 0.35, 150),
    "hard_hit_pct_against": np.random.uniform(0.3, 0.45, 150),
    "avg_ev_against": np.random.uniform(87, 91, 150),
    "sweet_spot_pct_against": np.random.uniform(0.28, 0.38, 150),
})
fake_official = {
    "games_played": 25, "games_started": 25, "innings_pitched_display": "140.1",
    "innings_pitched": 140.33, "wins": 9, "losses": 5, "saves": 0, "holds": 0,
    "era": 3.20, "whip": 1.05, "hits_allowed": 120, "earned_runs": 50,
    "walks": 40, "strikeouts": 160, "home_runs": 15, "hit_batsmen": 3,
    "batters_faced": 580, "k_per_9": 10.3, "bb_per_9": 2.6, "hr_per_9": 1.0,
    "k_pct": 0.276, "bb_pct": 0.069, "fip": 3.4,
}

data_layer.load_player_universe = lambda season, force_refresh=False: fake_universe.copy()
data_layer.get_pitcher_pitch_log = lambda **kwargs: synthetic_pitcher_df.copy()
data_layer.attach_home_away = lambda df, season, sport_id, team_id_col="batter_team_id": df.assign(
    is_home=np.random.choice([True, False], size=len(df))
)
data_layer.get_pitcher_official_season_stats = lambda *a, **k: dict(fake_official)
data_layer.get_pitching_standard_leaderboard = lambda season, sport_id, force_refresh=False: fake_standard_pool.copy()
data_layer.get_pitching_savant_percentile_pool = lambda season, force_refresh=False: fake_savant_pool.copy()
data_layer.get_qualified_ip_thresholds = lambda season, sport_id: {"qualified_ip_threshold": 162.0, "relief_ip_floor": 20.0}

from streamlit.testing.v1 import AppTest  # noqa: E402

at = AppTest.from_file("views/pitcher_dashboard.py", default_timeout=60)
at.run()
assert not at.exception, f"Exception on initial run: {list(at.exception)}"

at.selectbox[0].select(0)
at.run()
assert not at.exception, f"Exception after selecting pitcher: {list(at.exception)}"

load_buttons = [b for b in at.button if b.label == "Load pitcher"]
assert load_buttons, "Load pitcher button not found"
load_buttons[0].click()
at.run()

exceptions = list(at.exception)
if exceptions:
    for e in exceptions:
        print("EXCEPTION:", e)
    raise SystemExit(1)

print("Titles:", [t.value for t in at.title])
print("Num metrics rendered:", len(at.get("metric")))
print("Num tabs:", len(at.tabs))
print("Warnings:", [w.value[:200] for w in at.warning])
print("\nPITCHER HAPPY PATH TEST PASSED — full pitcher view rendered with no exceptions.")
