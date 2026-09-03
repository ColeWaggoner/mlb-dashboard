"""
Drives the actual Streamlit app (via AppTest) through a full player load with
mocked data_layer functions, since we can't hit the real MLB/Savant APIs from
this sandbox. Confirms every tab/chart in app.py renders without raising.
"""
import numpy as np
import pandas as pd

import data_layer
from test_smoke import df as synthetic_df  # reuse the generator from test_smoke.py

# ── Build a fake player universe ─────────────────────────────────────────────
fake_universe = pd.DataFrame([
    {"player_id": 123456, "name": "Test Batter", "position": "OF", "team": "Seattle Mariners",
     "sport_id": 1, "level": "MLB", "display_name": "Test Batter  —  MLB"},
])

fake_standard_pool = pd.DataFrame({
    "avg": np.random.uniform(0.200, 0.320, 200),
    "obp": np.random.uniform(0.280, 0.400, 200),
    "slg": np.random.uniform(0.350, 0.550, 200),
    "ops": np.random.uniform(0.650, 0.950, 200),
    "k_pct": np.random.uniform(0.12, 0.32, 200),
    "bb_pct": np.random.uniform(0.05, 0.15, 200),
    "qualified": True,
})
fake_savant_pool = pd.DataFrame({
    "hard_hit_pct": np.random.uniform(0.25, 0.55, 200),
    "avg_ev": np.random.uniform(85, 95, 200),
    "chase_pct": np.random.uniform(0.2, 0.4, 200),
    "whiff_pct": np.random.uniform(0.15, 0.35, 200),
    "sweet_spot_pct": np.random.uniform(0.25, 0.4, 200),
})

data_layer.load_player_universe = lambda season, force_refresh=False: fake_universe.copy()
data_layer.get_batter_pitch_log = lambda **kwargs: synthetic_df.copy()
data_layer.attach_home_away = lambda df, season, sport_id: df.assign(
    is_home=np.random.choice([True, False], size=len(df))
)
data_layer.get_standard_leaderboard = lambda season, sport_id, force_refresh=False: fake_standard_pool.copy()
data_layer.get_savant_percentile_pool = lambda season, force_refresh=False: fake_savant_pool.copy()
data_layer.get_qualified_pa_threshold = lambda season, sport_id: 300

from streamlit.testing.v1 import AppTest  # noqa: E402

at = AppTest.from_file("views/batter_dashboard.py", default_timeout=60)
at.run()
assert not at.exception, f"Exception on initial run: {list(at.exception)}"

# Select the (only) player and click Load
at.selectbox[0].select(0)
at.run()
assert not at.exception, f"Exception after selecting player: {list(at.exception)}"

at.button(key=None)  # noop, just to show buttons exist
load_buttons = [b for b in at.button if b.label == "Load batter"]
assert load_buttons, "Load batter button not found"
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
print("Num plotly charts:", len(at.get("plotly_chart") if at.get("plotly_chart") else []))
print("Warnings:", [w.value[:200] for w in at.warning])
print("\nHAPPY PATH TEST PASSED — full player view rendered with no exceptions.")
