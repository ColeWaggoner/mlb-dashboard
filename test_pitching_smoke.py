"""
Smoke test for stats_pitching.py / charts_pitching.py using a synthetic
pitch-level dataframe (same schema as api_scraper.get_data_df), since we
can't hit the live MLB API from this sandbox.
"""
import numpy as np
import pandas as pd

np.random.seed(7)

N = 900
pitch_types = ["Four-Seam Fastball", "Slider", "Changeup", "Curveball", "Sinker"]
PITCH_VELO_BASE = {
    "Four-Seam Fastball": 95, "Slider": 86, "Changeup": 84, "Curveball": 79, "Sinker": 94,
}
PITCH_IVB_BASE = {
    "Four-Seam Fastball": 16, "Slider": 2, "Changeup": 6, "Curveball": -8, "Sinker": 8,
}
PITCH_HB_BASE = {
    "Four-Seam Fastball": 6, "Slider": -4, "Changeup": 12, "Curveball": -8, "Sinker": 14,
}
events = [None] * 5 + ["single", "double", "home_run", "walk", "strikeout", "field_out", "hit_by_pitch"]

rows = []
game_dates = pd.date_range("2026-03-28", periods=140, freq="D")
for i in range(N):
    balls = np.random.randint(0, 4)
    strikes = np.random.randint(0, 3)
    is_last_pitch = np.random.random() < 0.25
    event_type = np.random.choice(events) if is_last_pitch else None
    pitch_desc = np.random.choice(pitch_types)
    is_swing = np.random.random() < 0.45
    is_whiff = is_swing and np.random.random() < 0.3
    in_play = is_swing and not is_whiff and np.random.random() < 0.35
    launch_speed = np.random.uniform(60, 108) if in_play else None
    launch_angle = np.random.uniform(-30, 50) if in_play else None
    trajectory = np.random.choice(["fly_ball", "ground_ball", "line_drive", "popup"]) if in_play else None

    rows.append({
        "game_id": 800000 + (i // 15),
        "game_date": str(game_dates[(i // 15) % len(game_dates)].date()),
        "batter_id": 555000 + i % 40,
        "batter_name": f"Batter {i % 40}",
        "batter_hand": np.random.choice(["L", "R"], p=[0.35, 0.65]),
        "batter_team": "OAK",
        "batter_team_id": 133,
        "pitcher_id": 987654,
        "pitcher_name": "Test Pitcher",
        "pitcher_hand": "R",
        "pitcher_team": "SEA",
        "pitcher_team_id": 136,
        "ab_number": i // 4,
        "inning": np.random.randint(1, 9),
        "play_description": "Swinging Strike" if is_whiff else ("Ball" if not is_swing else "Foul"),
        "play_code": "S" if is_whiff else ("B" if not is_swing else "F"),
        "in_play": in_play if event_type not in ("walk", "strikeout", "hit_by_pitch") else False,
        "is_strike": is_swing or np.random.random() < 0.4,
        "is_swing": True if is_swing else None,
        "is_whiff": True if is_whiff else None,
        "pitch_type": pitch_desc[:2].upper(),
        "pitch_description": pitch_desc,
        "strikes": strikes,
        "balls": balls,
        "outs": np.random.randint(0, 3),
        "start_speed": np.random.normal(PITCH_VELO_BASE[pitch_desc], 1.2),
        "end_speed": np.random.uniform(70, 90),
        "sz_top": 3.4, "sz_bot": 1.5,
        "px": np.random.uniform(-2, 2),
        "pz": np.random.uniform(0.8, 4.5),
        "x0": np.random.normal(-1.8, 0.15),
        "y0": 55.0,
        "z0": np.random.normal(5.9, 0.15),
        "zone": np.random.randint(1, 15),
        "extension": np.random.normal(6.5, 0.2),
        "spin_rate": np.random.normal(2200, 150),
        "spin_direction": None,
        "vb": None,
        "ivb": np.random.normal(PITCH_IVB_BASE[pitch_desc], 1.5),
        "hb": np.random.normal(PITCH_HB_BASE[pitch_desc], 1.5),
        "launch_speed": launch_speed,
        "launch_angle": launch_angle,
        "launch_distance": np.random.uniform(50, 420) if in_play else None,
        "trajectory": trajectory,
        "hit_x": np.random.uniform(60, 200) if in_play else None,
        "hit_y": np.random.uniform(60, 200) if in_play else None,
        "index_play": i, "play_id": str(i),
        "event": event_type,
        "event_type": event_type,
    })

df = pd.DataFrame(rows)
print("Synthetic pitcher df shape:", df.shape)

import stats
import stats_pitching
import charts
import charts_pitching

velo_summary = stats_pitching.compute_pitch_velocity_summary(df)
print("\nvelo_summary:\n", velo_summary[["pitch_type", "n_pitches", "usage_pct", "avg_velo", "avg_ivb", "avg_hb"]])

df["is_home"] = np.random.choice([True, False], size=len(df))
splits = stats_pitching.compute_pitcher_splits(df)
print("\nsplits keys:", list(splits.keys()))
for k, v in splits.items():
    print(f"  {k}: PA={v['n_pa']} AVG={v['ba']}")

trend = stats_pitching.compute_pitcher_rolling_trend(df, window=25)
print("\nrolling trend rows:", len(trend))

mix_by_count = stats_pitching.compute_pitch_mix_by_count(df)
print("\nmix_by_count rows:", len(mix_by_count))
print(mix_by_count.head(10))

# ── Percentile table (fake pools) ────────────────────────────────────────────
fake_official = {
    "era": 3.20, "whip": 1.05, "k_pct": 0.28, "bb_pct": 0.07, "k_bb_pct": 0.21,
    "hr_per_9": 1.0, "fip": 3.40, "innings_pitched": 140,
}
discipline = stats.compute_plate_discipline(df)
statcast = stats.compute_statcast_summary(df)
fake_official.update({
    "whiff_pct": discipline["whiff_pct"],
    "chase_pct": discipline["chase_pct"],
    "hard_hit_pct_against": statcast["hard_hit_pct"],
    "avg_ev_against": statcast["avg_ev"],
    "sweet_spot_pct_against": statcast["sweet_spot_pct"],
})

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

pct_table = stats_pitching.build_pitching_percentile_table(
    fake_official, fake_standard_pool, fake_savant_pool, is_mlb=True, use_relief_pool=False
)
print("\npercentile table (qualified pool):\n", pct_table)

pct_table_relief = stats_pitching.build_pitching_percentile_table(
    fake_official, fake_standard_pool, fake_savant_pool, is_mlb=True, use_relief_pool=True
)
print("\npercentile table (relief pool):\n", pct_table_relief)

pct_table_minor = stats_pitching.build_pitching_percentile_table(
    fake_official, fake_standard_pool, pd.DataFrame(), is_mlb=False, use_relief_pool=False
)
print("\npercentile table (minor, no savant):\n", pct_table_minor)

# ── Charts ────────────────────────────────────────────────────────────────────
figs = {
    "velocity_by_pitch": charts_pitching.velocity_by_pitch_chart(df),
    "movement_plot": charts_pitching.movement_plot(df),
    "release_point": charts_pitching.release_point_chart(df),
    "pitch_mix_by_count": charts_pitching.pitch_mix_by_count_chart(mix_by_count),
    "rolling_trend_pitcher": charts_pitching.rolling_trend_pitcher_chart(trend, 25),
    "zone_chart_reused": charts.zone_chart(df),
    "ev_la_reused": charts.ev_la_scatter(stats.enrich_spray_coordinates(df, "R")),
    "discipline_heatmap_reused": charts.discipline_heatmap(df),
    "percentile_bars_qualified": charts.percentile_bars(pct_table),
    "percentile_bars_relief": charts.percentile_bars(pct_table_relief),
}
for name, fig in figs.items():
    assert fig is not None
    _ = fig.to_dict()
    print(f"chart '{name}' OK, {len(fig.data)} traces")

# ── Edge cases ────────────────────────────────────────────────────────────────
empty = df.iloc[0:0]
print("\nempty velo_summary empty?", stats_pitching.compute_pitch_velocity_summary(empty).empty)
print("empty splits:", stats_pitching.compute_pitcher_splits(empty))
print("empty trend empty?", stats_pitching.compute_pitcher_rolling_trend(empty).empty)
_ = charts_pitching.velocity_by_pitch_chart(empty)
_ = charts_pitching.movement_plot(empty)
_ = charts_pitching.release_point_chart(empty)
_ = charts_pitching.rolling_trend_pitcher_chart(stats_pitching.compute_pitcher_rolling_trend(empty), 25)
print("EMPTY DF EDGE CASES OK")

# ── compute_pitcher_multi_rolling_trend: cross-check against the underlying
# generic engine directly, proving the label translation doesn't change any
# values, only the column names ────────────────────────────────────────────
_selected_pitcher_labels = ["AVG Against", "Whiff% Induced", "Hard-Hit% Against", "Avg Exit Velo Against"]
_selected_base_names = ["AVG", "Whiff%", "Hard-Hit%", "Avg Exit Velo"]
_pitcher_trend = stats_pitching.compute_pitcher_multi_rolling_trend(df, window=25, stat_names=_selected_pitcher_labels)
_base_trend = stats.compute_multi_rolling_trend(df, window=25, stat_names=_selected_base_names)
assert list(_pitcher_trend.columns) == ["game_date"] + _selected_pitcher_labels
for _label, _base in zip(_selected_pitcher_labels, _selected_base_names):
    pd.testing.assert_series_equal(
        _pitcher_trend[_label].reset_index(drop=True), _base_trend[_base].reset_index(drop=True), check_names=False
    )
print("compute_pitcher_multi_rolling_trend: exactly matches the underlying generic engine, correctly relabeled")

_pitcher_chart = charts.multi_rolling_trend_chart(
    _pitcher_trend, _selected_pitcher_labels, window=25, format_map=stats_pitching.PITCHER_TREND_STAT_FORMAT
)
assert len(_pitcher_chart.data) == len(_selected_pitcher_labels)
assert "%{y:.1f} mph" in _pitcher_chart.data[3].hovertemplate  # Avg Exit Velo Against
print("Pitcher-framed multi_rolling_trend_chart: renders correctly with the pitcher format map")

print("\nALL PITCHING SMOKE TESTS PASSED")
