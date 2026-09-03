"""
Smoke test using a synthetic pitch-level dataframe that mimics the real
schema from api_scraper.get_data_df, since we can't hit the live MLB API
from this sandbox. Exercises every function in stats.py and charts.py.
"""
import numpy as np
import pandas as pd

np.random.seed(42)

N = 600
pitch_types = ["Four-Seam Fastball", "Slider", "Changeup", "Curveball", "Sinker"]
events = [None] * 5 + ["single", "double", "triple", "home_run", "walk",
                       "strikeout", "field_out", "hit_by_pitch", "sac_fly"]

rows = []
game_dates = pd.date_range("2026-03-28", periods=140, freq="D")
for i in range(N):
    balls = np.random.randint(0, 4)
    strikes = np.random.randint(0, 3)
    is_last_pitch = np.random.random() < 0.25
    event_type = np.random.choice(events) if is_last_pitch else None
    pitch_desc = np.random.choice(pitch_types)
    is_swing = np.random.random() < 0.45
    is_whiff = is_swing and np.random.random() < 0.25
    in_play = is_swing and not is_whiff and np.random.random() < 0.35
    launch_speed = np.random.uniform(60, 112) if in_play else None
    launch_angle = np.random.uniform(-30, 50) if in_play else None
    hit_x = np.random.uniform(60, 200) if in_play else None
    hit_y = np.random.uniform(60, 200) if in_play else None
    trajectory = np.random.choice(["fly_ball", "ground_ball", "line_drive", "popup"]) if in_play else None

    rows.append({
        "game_id": 700000 + (i // 5),
        "game_date": str(game_dates[(i // 5) % len(game_dates)].date()),
        "batter_id": 123456,
        "batter_name": "Test Batter",
        "batter_hand": "R",
        "batter_team": "SEA",
        "batter_team_id": 136,
        "pitcher_id": 999000 + i % 30,
        "pitcher_name": f"Pitcher {i % 30}",
        "pitcher_hand": np.random.choice(["L", "R"], p=[0.3, 0.7]),
        "pitcher_team": "OAK",
        "pitcher_team_id": 133,
        "ab_number": i // 5,
        "inning": np.random.randint(1, 9),
        "play_description": "Swinging Strike" if is_whiff else ("Ball" if not is_swing else "Foul"),
        "play_code": "S" if is_whiff else ("B" if not is_swing else "F"),
        "in_play": in_play if event_type not in ("walk", "strikeout", "hit_by_pitch") else False,
        "is_strike": is_swing or np.random.random() < 0.4,
        "is_swing": True if is_swing else None,
        "is_whiff": True if is_whiff else None,
        "is_out": None,
        "is_ball": None,
        "is_review": None,
        "pitch_type": pitch_desc[:2].upper(),
        "pitch_description": pitch_desc,
        "strikes": strikes,
        "balls": balls,
        "outs": np.random.randint(0, 3),
        "strikes_after": min(strikes + 1, 2),
        "balls_after": min(balls + 1, 3),
        "outs_after": np.random.randint(0, 3),
        "start_speed": np.random.uniform(78, 99),
        "end_speed": np.random.uniform(70, 90),
        "sz_top": 3.4,
        "sz_bot": 1.5,
        "x": None, "y": None, "ax": None, "ay": None, "az": None,
        "pfxx": None, "pfxz": None,
        "px": np.random.uniform(-2, 2),
        "pz": np.random.uniform(0.8, 4.5),
        "vx0": None, "vy0": None, "vz0": None, "x0": None, "y0": None, "z0": None,
        "zone": np.random.randint(1, 15),
        "type_confidence": None, "plate_time": None, "extension": None,
        "spin_rate": None, "spin_direction": None, "vb": None, "ivb": None, "hb": None,
        "launch_speed": launch_speed,
        "launch_angle": launch_angle,
        "launch_distance": np.random.uniform(50, 420) if in_play else None,
        "launch_location": None,
        "trajectory": trajectory,
        "hardness": None,
        "hit_x": hit_x,
        "hit_y": hit_y,
        "index_play": i, "play_id": str(i), "start_time": None, "end_time": None,
        "is_pitch": True, "type_type": "pitch",
        "type_ab": None,
        "event": event_type,
        "event_type": event_type,
        "rbi": None, "away_score": None, "home_score": None,
    })

df = pd.DataFrame(rows)
print("Synthetic df shape:", df.shape)

import stats
import charts

slash = stats.compute_slash_line(df)
print("slash:", slash)

statcast = stats.compute_statcast_summary(df)
print("statcast:", statcast)

discipline = stats.compute_plate_discipline(df)
print("discipline:", discipline)

enriched = stats.enrich_spray_coordinates(df, batter_hand="R")
assert "x_ft" in enriched.columns and "field_side" in enriched.columns
print("enriched sample field_side counts:\n", enriched["field_side"].value_counts())

bb_profile = stats.compute_batted_ball_profile(enriched)
print("bb_profile:", bb_profile)

pitch_table = stats.compute_pitch_type_table(df)
print("pitch_table:\n", pitch_table)

swing_grid, contact_grid, count_n = stats.compute_count_matrix(df)
print("swing_grid ok:", swing_grid.shape, count_n.sum())
print("contact_grid ok:", contact_grid.shape)

contact_profile = stats.compute_contact_profile(df)
print("contact_profile:\n", contact_profile)

orphan_check = stats.compute_orphaned_at_bats(df)
print("orphan_check:", orphan_check)
# Note: this synthetic fixture assigns event_type independently per row
# rather than guaranteeing one terminal row per at-bat group, so a nonzero
# count here is a fixture artifact, not a signal about the real function —
# compute_orphaned_at_bats itself is validated with exact hand-built cases
# directly, not against this loosely-random generator.

iz_contact_grid, iz_swing_n, oz_contact_grid, oz_swing_n = stats.compute_contact_rate_matrix_by_zone(df)
print("in-zone contact grid shape:", iz_contact_grid.shape, "total swings:", iz_swing_n.sum())
print("out-of-zone contact grid shape:", oz_contact_grid.shape, "total swings:", oz_swing_n.sum())

trend = stats.compute_rolling_trend(df, window=25)
print("trend rows:", len(trend))

df["is_home"] = np.random.choice([True, False], size=len(df))
splits = stats.compute_splits(df)
print("splits keys:", list(splits.keys()))

# Fake league pools for percentile testing
standard_pool = pd.DataFrame({
    "avg": np.random.uniform(0.200, 0.320, 200),
    "obp": np.random.uniform(0.280, 0.400, 200),
    "slg": np.random.uniform(0.350, 0.550, 200),
    "ops": np.random.uniform(0.650, 0.950, 200),
    "k_pct": np.random.uniform(0.12, 0.32, 200),
    "bb_pct": np.random.uniform(0.05, 0.15, 200),
    "qualified": True,
})
savant_pool = pd.DataFrame({
    "hard_hit_pct": np.random.uniform(0.25, 0.55, 200),
    "avg_ev": np.random.uniform(85, 95, 200),
    "chase_pct": np.random.uniform(0.2, 0.4, 200),
    "whiff_pct": np.random.uniform(0.15, 0.35, 200),
    "sweet_spot_pct": np.random.uniform(0.25, 0.4, 200),
})

combined = {**slash, **statcast, **discipline}
import data_layer  # noqa
pct_table = stats.build_percentile_table(combined, standard_pool, savant_pool, is_mlb=True)
print("percentile table:\n", pct_table)

pct_table_minor = stats.build_percentile_table(combined, standard_pool, pd.DataFrame(), is_mlb=False)
print("percentile table (minor, no savant):\n", pct_table_minor)

# ── Charts: just verify they build without raising ──────────────────────────
figs = {
    "spray": charts.spray_chart(enriched),
    "zone": charts.zone_chart(df),
    "pitch_mix": charts.pitch_mix_chart(pitch_table),
    "ev_la": charts.ev_la_scatter(enriched),
    "discipline_heatmap": charts.discipline_heatmap(df),
    "count_heatmap": charts.count_heatmap(swing_grid, count_n),
    "contact_rate_count_heatmap": charts.count_heatmap(contact_grid, count_n, label="Contact%", title="Contact Rate by Count"),
    "contact_profile_chart": charts.contact_profile_chart(contact_profile),
    "in_zone_contact_by_count": charts.count_heatmap(iz_contact_grid, iz_swing_n, label="Contact%", title="In-Zone Contact Rate by Count"),
    "out_zone_contact_by_count": charts.count_heatmap(oz_contact_grid, oz_swing_n, label="Contact%", title="Out-of-Zone Contact Rate by Count"),
    "percentile_bars": charts.percentile_bars(pct_table),
    "percentile_bars_minor": charts.percentile_bars(pct_table_minor),
    "rolling_trend": charts.rolling_trend_chart(trend, 25),
}
for name, fig in figs.items():
    assert fig is not None
    # Force serialization to catch any bad trace config
    _ = fig.to_dict()
    print(f"chart '{name}' OK, {len(fig.data)} traces")

# ── Edge cases: empty dataframe ──────────────────────────────────────────────
empty = df.iloc[0:0]
print("empty slash:", stats.compute_slash_line(empty))
print("empty statcast:", stats.compute_statcast_summary(empty))
print("empty discipline:", stats.compute_plate_discipline(empty))
print("empty pitch table empty?", stats.compute_pitch_type_table(empty).empty)
_ = charts.spray_chart(stats.enrich_spray_coordinates(empty, "R"))
_ = charts.zone_chart(empty)
_ = charts.rolling_trend_chart(stats.compute_rolling_trend(empty), 25)
_ = charts.contact_profile_chart(stats.compute_contact_profile(empty))
_empty_swing_grid, _empty_contact_grid, _empty_count_n = stats.compute_count_matrix(empty)
_ = charts.count_heatmap(_empty_contact_grid, _empty_count_n, label="Contact%", title="Contact Rate by Count")
_e_iz_c, _e_iz_n, _e_oz_c, _e_oz_n = stats.compute_contact_rate_matrix_by_zone(empty)
_ = charts.count_heatmap(_e_iz_c, _e_iz_n, label="Contact%", title="In-Zone Contact Rate by Count")
_ = charts.count_heatmap(_e_oz_c, _e_oz_n, label="Contact%", title="Out-of-Zone Contact Rate by Count")
print("EMPTY DF EDGE CASES OK")


# ─────────────────────────────────────────────────────────────────────────────
# compute_multi_rolling_trend cross-check: every stat it computes must match
# the equivalent already-tested reference function exactly when the rolling
# window covers the whole (small, hand-built) dataset — i.e. the "rolling"
# value at the last point should equal the plain full-sample aggregate.
# ─────────────────────────────────────────────────────────────────────────────
_trend_rows = []
_gid = 1


def _add_pitch(ab_n, is_swing, is_whiff, in_zone, is_strike, balls=0, strikes=0, in_play=False,
               event_type=None, launch_speed=np.nan, launch_angle=np.nan):
    _trend_rows.append({
        "game_id": _gid, "game_date": "2026-04-01", "ab_number": ab_n,
        "pitch_description": "Four-Seam Fastball",
        "is_swing": is_swing, "is_whiff": is_whiff, "is_strike": is_strike,
        "px": 0.0 if in_zone else 1.5, "pz": 2.4, "sz_top": 3.4, "sz_bot": 1.5,
        "balls": balls, "strikes": strikes,
        "in_play": in_play, "event_type": event_type, "rbi": 0,
        "launch_speed": launch_speed, "launch_angle": launch_angle,
    })


_add_pitch(0, True, False, True, True, in_play=True, event_type="single", launch_speed=98, launch_angle=15)
_add_pitch(1, True, True, True, True)
_add_pitch(1, True, True, False, True, strikes=1, event_type="strikeout")
for _i in range(4):
    _add_pitch(2, False, False, False, False, balls=_i, event_type="walk" if _i == 3 else None)
_add_pitch(3, True, False, True, True, in_play=True, event_type="home_run", launch_speed=105, launch_angle=28)
_add_pitch(4, True, False, True, True)
_add_pitch(4, True, False, True, True, strikes=1, in_play=True, event_type="field_out", launch_speed=80, launch_angle=-5)

_trend_df = pd.DataFrame(_trend_rows)
_ref_slash = stats.compute_slash_line(_trend_df)
_ref_disc = stats.compute_plate_discipline(_trend_df)
_ref_sc = stats.compute_statcast_summary(_trend_df)

_multi = stats.compute_multi_rolling_trend(_trend_df, window=5, stat_names=stats.TREND_STAT_OPTIONS)
_last = _multi.iloc[-1]

assert abs(_last["AVG"] - _ref_slash["ba"]) < 1e-9
assert abs(_last["OBP"] - _ref_slash["obp"]) < 1e-9
assert abs(_last["SLG"] - _ref_slash["slg"]) < 1e-9
assert abs(_last["OPS"] - _ref_slash["ops"]) < 1e-9
assert abs(_last["ISO"] - (_ref_slash["slg"] - _ref_slash["ba"])) < 1e-9
assert abs(_last["K%"] - _ref_slash["k_pct"]) < 1e-9
assert abs(_last["BB%"] - _ref_slash["bb_pct"]) < 1e-9
assert abs(_last["Whiff%"] - _ref_disc["whiff_pct"]) < 1e-9
assert abs(_last["Whiff% (in zone)"] - 0.2) < 1e-9
assert abs(_last["Whiff% (out of zone)"] - 1.0) < 1e-9
assert abs(_last["Chase%"] - _ref_disc["chase_pct"]) < 1e-9
assert abs(_last["Zone%"] - _ref_disc["zone_pct"]) < 1e-9
assert abs(_last["Z-Swing%"] - _ref_disc["z_swing_pct"]) < 1e-9
assert abs(_last["Contact%"] - _ref_disc["contact_pct"]) < 1e-9
assert abs(_last["CSW%"] - _ref_disc["csw_pct"]) < 1e-9
assert abs(_last["Swing%"] - _ref_disc["swing_pct"]) < 1e-9
assert abs(_last["Hard-Hit%"] - _ref_sc["hard_hit_pct"]) < 1e-9
assert abs(_last["Sweet-Spot%"] - _ref_sc["sweet_spot_pct"]) < 1e-9
assert abs(_last["Avg Exit Velo"] - _ref_sc["avg_ev"]) < 1e-9
print("compute_multi_rolling_trend: every stat matches the already-tested reference functions exactly")

_ = charts.multi_rolling_trend_chart(_multi, ["AVG", "OPS"], window=5)
_ = charts.multi_rolling_trend_chart(_multi, ["AVG", "OPS", "Avg Exit Velo"], window=5)
_ = charts.multi_rolling_trend_chart(pd.DataFrame(), [], window=5)
print("multi_rolling_trend_chart: renders for 1/2/3-stat and empty cases with no exceptions")

print("\nALL SMOKE TESTS PASSED")
