"""
End-to-end test for the Full Season / Last N Games / Custom Range period
selector, using the real Lazaro Montes export as the data source so the
expected numbers are computed independently (via stats.filter_by_period +
stats.compute_slash_line directly) and then verified against what the
actual rendered UI shows after selecting each period option.
"""
import os

import numpy as np
import pandas as pd

import data_layer
import stats

CSV_PATH = os.path.join(os.path.dirname(__file__), "Lazaro_Montes_2026_raw_pitch_log.csv")
if not os.path.exists(CSV_PATH):
    print(f"SKIPPED — {CSV_PATH} not present in this environment (real data file, not shipped in the repo).")
    raise SystemExit(0)

real_df = pd.read_csv(CSV_PATH)

fake_universe = pd.DataFrame([
    {"player_id": 703155, "name": "Lazaro Montes", "position": "OF", "team": "Tacoma Rainiers",
     "sport_id": 11, "level": "AAA", "display_name": "Lazaro Montes  —  AAA"},
])
fake_standard_pool = pd.DataFrame({
    "avg": np.random.uniform(0.200, 0.320, 100), "obp": np.random.uniform(0.280, 0.400, 100),
    "slg": np.random.uniform(0.350, 0.550, 100), "ops": np.random.uniform(0.650, 0.950, 100),
    "k_pct": np.random.uniform(0.12, 0.32, 100), "bb_pct": np.random.uniform(0.05, 0.15, 100),
    "qualified": True,
})

data_layer.load_player_universe = lambda season, force_refresh=False: fake_universe.copy()
data_layer.get_batter_pitch_log = lambda **kwargs: real_df.copy()
data_layer.attach_home_away = lambda df, season, sport_id: df
data_layer.get_standard_leaderboard = lambda season, sport_id, force_refresh=False: fake_standard_pool.copy()
data_layer.get_savant_percentile_pool = lambda season, force_refresh=False: pd.DataFrame()
data_layer.get_qualified_pa_threshold = lambda season, sport_id: 300

from streamlit.testing.v1 import AppTest  # noqa: E402

at = AppTest.from_file("views/batter_dashboard.py", default_timeout=60)
at.run()
at.selectbox[0].select(0)
at.run()
at.button(key=None)
[b for b in at.button if b.label == "Load batter"][0].click()
at.run()
assert not at.exception, f"Exception on load: {list(at.exception)}"


def get_metrics():
    return {m.label: m.value for m in at.get("metric")}


# ── Default: Full Season ──────────────────────────────────────────────────────
metrics = get_metrics()
print("Full Season AVG/OBP/SLG:", metrics.get("AVG"), metrics.get("OBP"), metrics.get("SLG"))
assert metrics.get("AVG") == ".274", metrics.get("AVG")
assert metrics.get("OBP") == ".369", metrics.get("OBP")
assert metrics.get("SLG") == ".571", metrics.get("SLG")
print("FULL SEASON DEFAULT VERIFIED CORRECT")

# ── Switch to Last N Games ────────────────────────────────────────────────────
period_selectbox = at.selectbox(key="bat_period_choice")
period_selectbox.select("Last N Games")
at.run()
assert not at.exception, f"Exception after selecting Last N Games: {list(at.exception)}"

n_input = at.number_input(key="bat_period_n")
n_input.set_value(5)
at.run()
assert not at.exception, f"Exception after setting N=5: {list(at.exception)}"

expected = stats.compute_slash_line(stats.filter_by_period(real_df, "last_n", last_n_games=5))
metrics = get_metrics()
print("Last 5 Games AVG/OBP/SLG (UI):", metrics.get("AVG"), metrics.get("OBP"), metrics.get("SLG"))
print("Last 5 Games AVG/OBP/SLG (expected):",
      f"{expected['ba']:.3f}"[1:], f"{expected['obp']:.3f}"[1:], f"{expected['slg']:.3f}"[1:])

assert metrics.get("AVG") == f"{expected['ba']:.3f}"[1:]
assert metrics.get("OBP") == f"{expected['obp']:.3f}"[1:]
assert metrics.get("SLG") == f"{expected['slg']:.3f}"[1:]
print("LAST 5 GAMES VIA REAL UI VERIFIED CORRECT — matches independently computed oracle exactly.")

# ── Switch to Custom Range ────────────────────────────────────────────────────
period_selectbox2 = at.selectbox(key="bat_period_choice")
period_selectbox2.select("Custom Range")
at.run()
assert not at.exception, f"Exception after selecting Custom Range: {list(at.exception)}"

dates = pd.to_datetime(real_df["game_date"])
mid_date = dates.min() + (dates.max() - dates.min()) / 2

start_input = at.date_input(key="bat_period_start")
start_input.set_value(dates.min().date())
end_input = at.date_input(key="bat_period_end")
end_input.set_value(mid_date.date())
at.run()
assert not at.exception, f"Exception after setting custom range: {list(at.exception)}"

expected_custom = stats.compute_slash_line(
    stats.filter_by_period(real_df, "custom", start_date=dates.min().date(), end_date=mid_date.date())
)
metrics = get_metrics()
print("Custom range AVG (UI):", metrics.get("AVG"), "| expected:", f"{expected_custom['ba']:.3f}"[1:])
assert metrics.get("AVG") == f"{expected_custom['ba']:.3f}"[1:]
print("CUSTOM RANGE VIA REAL UI VERIFIED CORRECT.")

print("\nALL PERIOD SELECTOR END-TO-END TESTS PASSED")
