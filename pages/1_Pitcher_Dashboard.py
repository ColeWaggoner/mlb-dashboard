"""
Pitcher Dashboard — second page of the app (Streamlit auto-detects anything
in pages/ and adds it to the sidebar nav). Run the same way as the batter
page: streamlit run app.py, then switch pages in the sidebar.
"""

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

# app.py's directory (the project root) isn't automatically on sys.path for
# files inside pages/, so the shared modules need this before importing them.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import charts
import charts_pitching
import data_layer
import stats
import stats_pitching
import theme

st.set_page_config(page_title="Pitcher Dashboard", layout="wide", initial_sidebar_state="expanded")
theme.inject_theme(theme.ACCENTS["pitcher"])
ACCENT = theme.ACCENTS["pitcher"]

CURRENT_YEAR = date.today().year

for key, default in [
    ("pitcher_df", None), ("pitcher_meta", None), ("pitching_standard_pool", None),
    ("pitching_savant_pool", None), ("pitcher_official", None),
]:
    st.session_state.setdefault(key, default)


def fmt_rate(x, allow_negative=False):
    if pd.isna(x):
        return "—"
    if x < 0 and not allow_negative:
        return "—"
    s = f"{x:.3f}"
    if s.startswith("0."):
        return s[1:]
    if s.startswith("-0."):
        return "-" + s[2:]
    return s


# ── Sidebar: pitcher search ──────────────────────────────────────────────────
with st.sidebar:
    st.title("Pitcher Search")

    season = st.number_input("Season", min_value=2015, max_value=CURRENT_YEAR,
                              value=CURRENT_YEAR, step=1, key="p_season")

    level_names = list(data_layer.LEVELS.values())
    picked_levels = st.multiselect("Levels", level_names, default=level_names, key="p_levels")
    picked_sport_ids = [sid for sid, name in data_layer.LEVELS.items() if name in picked_levels]

    with st.spinner("Loading player list…"):
        universe = data_layer.load_player_universe(season)

    if not universe.empty and picked_sport_ids:
        universe = universe[universe["sport_id"].isin(picked_sport_ids)]
    # Pitchers only by default — two-way players (position "TWP") stay visible too.
    pitchers_only = st.checkbox("Pitchers only (uncheck to search everyone)", value=True)
    if pitchers_only and not universe.empty and "position" in universe.columns:
        universe = universe[universe["position"].isin(["P", "TWP"])]

    if universe.empty:
        st.warning("No player list loaded yet — this needs network access to "
                    "statsapi.mlb.com, so it only works when you run the app "
                    "locally, not in a sandboxed preview.")
        selected_row = None
    else:
        universe = universe.sort_values("name")
        options = universe.index.tolist()
        selected_idx = st.selectbox(
            "Pitcher", options, format_func=lambda i: universe.loc[i, "display_name"], key="p_player"
        )
        selected_row = universe.loc[selected_idx]

    force_refresh = st.checkbox("Force refresh this pitcher's data (re-pull all games)", value=False, key="p_refresh")
    load_clicked = st.button("Load pitcher", type="primary",
                              disabled=selected_row is None, key="p_load", width='stretch')

    st.divider()
    st.caption(
        "ERA/WHIP/W-L/IP come straight from MLB's official season stats for "
        "this pitcher. Everything pitch-level (mix, velocity, movement, "
        "location, discipline) is pulled from the live feed game-by-game, "
        "cached after the first look-up."
    )

# ── Load on click ─────────────────────────────────────────────────────────────
if load_clicked and selected_row is not None:
    status = st.empty()

    def progress(msg):
        status.info(msg)

    df = data_layer.get_pitcher_pitch_log(
        player_id=int(selected_row["player_id"]),
        player_name=selected_row["name"],
        season=int(season),
        sport_id=int(selected_row["sport_id"]),
        force_refresh=force_refresh,
        progress_callback=progress,
    )
    status.empty()

    if not df.empty:
        df = data_layer.attach_home_away(df, int(season), int(selected_row["sport_id"]),
                                          team_id_col="pitcher_team_id")

    st.session_state.pitcher_df = df
    st.session_state.pitcher_meta = selected_row.to_dict()

    with st.spinner("Loading official season stats and league baselines…"):
        try:
            st.session_state.pitcher_official = data_layer.get_pitcher_official_season_stats(
                int(selected_row["player_id"]), int(season), int(selected_row["sport_id"]),
                force_refresh=force_refresh,
            )
        except Exception as e:
            st.session_state.pitcher_official = {}
            st.warning(f"Couldn't load official season stats: {e}")

        try:
            st.session_state.pitching_standard_pool = data_layer.get_pitching_standard_leaderboard(
                int(season), int(selected_row["sport_id"])
            )
        except Exception as e:
            st.session_state.pitching_standard_pool = pd.DataFrame()
            st.warning(f"Couldn't load the pitching leaderboard for percentiles: {e}")

        if selected_row["sport_id"] == 1:
            try:
                st.session_state.pitching_savant_pool = data_layer.get_pitching_savant_percentile_pool(int(season))
            except Exception as e:
                st.session_state.pitching_savant_pool = pd.DataFrame()
                st.warning(f"Couldn't load Baseball Savant's pitching leaderboard: {e}")
        else:
            st.session_state.pitching_savant_pool = pd.DataFrame()


# ── Main content ──────────────────────────────────────────────────────────────
if st.session_state.pitcher_df is None:
    theme.page_header("Pitcher Dashboard", "Pick a pitcher to get started", "", ACCENT)
    st.markdown(
        "Pick a pitcher in the sidebar and hit **Load pitcher** to get started. "
        "Works for any MLB or minor-league pitcher (AAA/AA/High-A/Single-A) "
        "with tracked pitch-by-pitch data this season."
    )
    st.stop()

df = st.session_state.pitcher_df
meta = st.session_state.pitcher_meta
official = st.session_state.pitcher_official or {}

if df.empty and not official:
    theme.page_header(meta.get("level", ""), meta["name"], "No data loaded for this pitcher yet.", ACCENT)
    st.info("No data loaded for this pitcher yet.")
    st.stop()

is_mlb = meta["sport_id"] == 1

# ── Header ────────────────────────────────────────────────────────────────────
head_col1, head_col2 = st.columns([1, 5])
with head_col1:
    if is_mlb:
        st.image(
            f"https://img.mlbstatic.com/mlb-photos/image/upload/w_213,q_auto:best/v1/people/{meta['player_id']}/headshot/67/current",
            width=120,
        )
with head_col2:
    theme.page_header(
        "Pitcher Dashboard", meta["name"], f"{meta.get('team','') or ''} · {season} season",
        ACCENT, badge=meta.get("level"),
    )


# ── Filters ───────────────────────────────────────────────────────────────────
filt_col1, filt_col2, filt_col3, filt_col4 = st.columns(4)
with filt_col1:
    pitch_options = sorted(df["pitch_description"].dropna().unique().tolist()) if not df.empty else []
    picked_pitches = st.multiselect("Pitch types", pitch_options, default=pitch_options)
with filt_col2:
    hand_filter = st.radio("Batter hand", ["Both", "vs LHH", "vs RHH"], horizontal=True)
with filt_col3:
    if not df.empty and "is_home" in df.columns and df["is_home"].notna().any():
        loc_filter = st.radio("Location", ["Both", "Home", "Away"], horizontal=True)
    else:
        loc_filter = "Both"
with filt_col4:
    roll_window = st.slider("Rolling window (PA)", min_value=10, max_value=75, value=25, step=5)

if not df.empty:
    filtered = df[df["pitch_description"].isin(picked_pitches)] if picked_pitches else df.iloc[0:0]
    if hand_filter == "vs LHH":
        filtered = filtered[filtered["batter_hand"] == "L"]
    elif hand_filter == "vs RHH":
        filtered = filtered[filtered["batter_hand"] == "R"]
    if loc_filter == "Home":
        filtered = filtered[filtered["is_home"] == True]  # noqa: E712
    elif loc_filter == "Away":
        filtered = filtered[filtered["is_home"] == False]  # noqa: E712
else:
    filtered = df

# ── Stat tiles: official season line ─────────────────────────────────────────
t1, t2, t3, t4, t5, t6 = st.columns(6)
t1.metric("ERA", f"{official.get('era'):.2f}" if official.get("era") is not None and pd.notna(official.get("era")) else "—")
t2.metric("WHIP", f"{official.get('whip'):.2f}" if official.get("whip") is not None and pd.notna(official.get("whip")) else "—")
t3.metric("W-L", f"{official.get('wins', '—')}-{official.get('losses', '—')}")
t4.metric("SV / HLD", f"{official.get('saves', 0)} / {official.get('holds', 0)}")
t5.metric("IP", official.get("innings_pitched_display", "—"))
t6.metric("K%", f"{official.get('k_pct')*100:.1f}%" if official.get("k_pct") is not None and pd.notna(official.get("k_pct")) else "—")

t7, t8, t9, t10, t11, t12 = st.columns(6)
t7.metric("BB%", f"{official.get('bb_pct')*100:.1f}%" if official.get("bb_pct") is not None and pd.notna(official.get("bb_pct")) else "—")
t8.metric("K/9", f"{official.get('k_per_9', 0):.1f}" if official.get("k_per_9") is not None else "—")
t9.metric("BB/9", f"{official.get('bb_per_9', 0):.1f}" if official.get("bb_per_9") is not None else "—")
t10.metric("HR/9", f"{official.get('hr_per_9', 0):.1f}" if official.get("hr_per_9") is not None else "—")
t11.metric("FIP (approx)", f"{official.get('fip'):.2f}" if official.get("fip") is not None and pd.notna(official.get("fip")) else "—")
t12.metric("Batters Faced", official.get("batters_faced", "—"))

st.caption("ERA/WHIP/W-L/SV/IP/FIP are the official season totals for this pitcher, independent of the filters above. "
           "Everything below (charts, splits, percentile 'induced/against' rows) reflects the current pitch-type/hand/location filter.")

# ── Percentile ranks ──────────────────────────────────────────────────────────
theme.section_title("Percentile Rankings", ACCENT)

qual_thresholds = data_layer.get_qualified_ip_thresholds(int(season), int(meta["sport_id"]))
own_ip = official.get("innings_pitched", 0) or 0
use_relief_pool = own_ip < qual_thresholds.get("qualified_ip_threshold", 0)

pitcher_stats_for_pct = dict(official)
discipline_filtered = stats.compute_plate_discipline(filtered) if not filtered.empty else {}
statcast_against = stats.compute_statcast_summary(filtered) if not filtered.empty else {}
pitcher_stats_for_pct.update({
    "whiff_pct": discipline_filtered.get("whiff_pct"),
    "chase_pct": discipline_filtered.get("chase_pct"),
    "hard_hit_pct_against": statcast_against.get("hard_hit_pct"),
    "avg_ev_against": statcast_against.get("avg_ev"),
    "sweet_spot_pct_against": statcast_against.get("sweet_spot_pct"),
})

pct_table = stats_pitching.build_pitching_percentile_table(
    pitcher_stats_for_pct, st.session_state.pitching_standard_pool,
    st.session_state.pitching_savant_pool, is_mlb, use_relief_pool=use_relief_pool,
)
st.plotly_chart(charts.percentile_bars(pct_table), width='stretch')

if use_relief_pool:
    st.caption(f"This pitcher's IP ({own_ip:.1f}) is below the official qualified threshold "
               f"({qual_thresholds.get('qualified_ip_threshold', 0):.0f} IP, mirroring the ERA-title rule), "
               f"so ERA/WHIP/K%/BB%/HR9/FIP percentiles are shown against a broader relief-eligible pool "
               f"({qual_thresholds.get('relief_ip_floor', 0):.0f}+ IP) instead — otherwise almost no reliever "
               "would ever show a percentile at all.")
if not is_mlb:
    st.caption("Statcast-based percentiles (Whiff%, Chase%, Hard-Hit%-against, Exit Velo-against, Sweet-Spot%-against) "
               "are only available for MLB — Baseball Savant doesn't publish minor-league leaderboards.")

with st.expander("Data source status (debug info)"):
    std_pool = st.session_state.pitching_standard_pool
    sav_pool = st.session_state.pitching_savant_pool
    if std_pool is None or std_pool.empty:
        std_summary = "not loaded"
    else:
        std_summary = (f"{len(std_pool)} pitchers, {int(std_pool['qualified'].sum())} qualified, "
                        f"{int(std_pool['relief_pool'].sum())} relief-eligible")
    st.write(f"**Standard pitching leaderboard (MLB Stats API):** {std_summary}")
    if std_pool is not None and not std_pool.empty:
        st.caption(f"Columns: {list(std_pool.columns)}")
    sav_summary = "not loaded" if sav_pool is None or sav_pool.empty else f"{len(sav_pool)} pitchers"
    st.write(f"**Baseball Savant pitching leaderboard (MLB only):** {sav_summary}")
    if sav_pool is not None and not sav_pool.empty:
        st.caption(f"Columns: {list(sav_pool.columns)}")
    st.dataframe(pct_table, width='stretch', hide_index=True)

st.divider()

if filtered.empty:
    st.info("No pitch-level data for the current filter selection — try widening the pitch-type/hand/location filters above.")
    st.stop()

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_mix, tab_shape, tab_location, tab_discipline, tab_contact, tab_trend, tab_splits, tab_raw = st.tabs(
    ["Pitch Mix", "Velocity & Movement", "Location", "Plate Discipline",
     "Contact Allowed", "Trends", "Splits", "Raw Data"]
)

with tab_mix:
    velo_summary = stats_pitching.compute_pitch_velocity_summary(filtered)
    c1, c2 = st.columns([1, 1.3])
    with c1:
        pitch_table = stats.compute_pitch_type_table(filtered)
        st.plotly_chart(charts.pitch_mix_chart(pitch_table), width='stretch')
    with c2:
        st.markdown("**Velocity / spin / movement by pitch type**")
        if not velo_summary.empty:
            show = velo_summary[["pitch_type", "n_pitches", "usage_pct", "avg_velo", "max_velo",
                                  "avg_spin", "avg_ivb", "avg_hb"]].copy()
            show["usage_pct"] = show["usage_pct"].map(lambda v: f"{v:.0f}%")
            for c in ["avg_velo", "max_velo"]:
                show[c] = show[c].map(lambda v: f"{v:.1f}" if pd.notna(v) else "—")
            for c in ["avg_spin", "avg_ivb", "avg_hb"]:
                show[c] = show[c].map(lambda v: f"{v:.0f}" if pd.notna(v) else "—")
            show.columns = ["Pitch", "N", "Usage%", "Avg Velo", "Max Velo", "Avg Spin", "Avg IVB", "Avg HB"]
            st.dataframe(show, width='stretch', hide_index=True)
        else:
            st.info("No velocity data for this filter.")

    st.markdown("**Pitch mix by count situation**")
    mix_by_count = stats_pitching.compute_pitch_mix_by_count(filtered)
    st.plotly_chart(charts_pitching.pitch_mix_by_count_chart(mix_by_count), width='stretch')

with tab_shape:
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(charts_pitching.velocity_by_pitch_chart(filtered), width='stretch')
    with c2:
        st.plotly_chart(charts_pitching.release_point_chart(filtered), width='stretch')
    st.plotly_chart(charts_pitching.movement_plot(filtered), width='stretch')

with tab_location:
    st.plotly_chart(charts.zone_chart(filtered), width='stretch')
    st.caption("Same zone chart as the batter dashboard, from the pitcher's side: every pitch thrown, colored by type, "
               "with a glow on the ones that got hit hard.")

with tab_discipline:
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(charts.discipline_heatmap(filtered), width='stretch')
    with c2:
        swing_grid, contact_grid, count_n = stats.compute_count_matrix(filtered)
        st.plotly_chart(charts.count_heatmap(swing_grid, count_n), width='stretch')

    discipline = stats.compute_plate_discipline(filtered)
    d1, d2, d3, d4, d5 = st.columns(5)
    d1.metric("Zone%", f"{discipline['zone_pct']*100:.1f}%" if pd.notna(discipline["zone_pct"]) else "—")
    d2.metric("Chase% (induced)", f"{discipline['chase_pct']*100:.1f}%" if pd.notna(discipline["chase_pct"]) else "—")
    d3.metric("Whiff% (induced)", f"{discipline['whiff_pct']*100:.1f}%" if pd.notna(discipline["whiff_pct"]) else "—")
    d4.metric("CSW%", f"{discipline['csw_pct']*100:.1f}%" if pd.notna(discipline["csw_pct"]) else "—")
    d5.metric("1st-Pitch Strike%", f"{discipline['first_pitch_strike_pct']*100:.1f}%"
              if pd.notna(discipline["first_pitch_strike_pct"]) else "—")
    st.caption("Unlike a hitter's own Chase%/Whiff% (bad for them), these are GOOD for a pitcher — "
               "they mean batters are missing and expanding the zone against this pitcher.")

with tab_contact:
    statcast = stats.compute_statcast_summary(filtered)
    bb_profile = stats.enrich_spray_coordinates(filtered, batter_hand="R")  # side/pull framing not meaningful here
    bb_profile_summary = stats.compute_batted_ball_profile(bb_profile)
    c1, c2 = st.columns([1, 1])
    with c1:
        st.plotly_chart(charts.ev_la_scatter(filtered), width='stretch')
    with c2:
        st.markdown("**Contact quality allowed**")
        b1, b2, b3 = st.columns(3)
        b1.metric("Hard-Hit% allowed", f"{statcast['hard_hit_pct']*100:.1f}%" if pd.notna(statcast["hard_hit_pct"]) else "—")
        b2.metric("Avg Exit Velo allowed", f"{statcast['avg_ev']:.1f} mph" if pd.notna(statcast["avg_ev"]) else "—")
        b3.metric("Sweet-Spot% allowed", f"{statcast['sweet_spot_pct']*100:.1f}%" if pd.notna(statcast["sweet_spot_pct"]) else "—")
        b4, b5, b6, b7 = st.columns(4)
        b4.metric("GB%", f"{bb_profile_summary['gb_pct']*100:.0f}%" if pd.notna(bb_profile_summary["gb_pct"]) else "—")
        b5.metric("FB%", f"{bb_profile_summary['fb_pct']*100:.0f}%" if pd.notna(bb_profile_summary["fb_pct"]) else "—")
        b6.metric("LD%", f"{bb_profile_summary['ld_pct']*100:.0f}%" if pd.notna(bb_profile_summary["ld_pct"]) else "—")
        b7.metric("PU%", f"{bb_profile_summary['pu_pct']*100:.0f}%" if pd.notna(bb_profile_summary["pu_pct"]) else "—")

with tab_trend:
    trend_df = stats_pitching.compute_pitcher_rolling_trend(df, window=roll_window)
    st.plotly_chart(charts_pitching.rolling_trend_pitcher_chart(trend_df, roll_window), width='stretch')
    st.caption("Trend line always uses the full season regardless of the pitch-type/hand/location filters above. "
               "No rolling ERA — earned vs. unearned runs isn't reliably recoverable from play-by-play data.")

with tab_splits:
    splits = stats_pitching.compute_pitcher_splits(df)
    if not splits:
        st.info("Not enough data to compute splits.")
    else:
        rows = []
        for label, s in splits.items():
            rows.append({
                "Split": label, "PA": s["n_pa"], "AB": s["n_ab"],
                "AVG-against": fmt_rate(s["ba"]),
                "OBP-against": fmt_rate(s["obp"]),
                "SLG-against": fmt_rate(s["slg"]),
                "OPS-against": fmt_rate(s["ops"], allow_negative=True),
                "K%": f"{s['k_pct']*100:.1f}%" if pd.notna(s["k_pct"]) else "—",
                "BB%": f"{s['bb_pct']*100:.1f}%" if pd.notna(s["bb_pct"]) else "—",
            })
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

with tab_raw:
    st.markdown("Underlying pitch-level table for the current filter selection.")
    st.dataframe(filtered, width='stretch', height=500)
    st.download_button(
        "Download filtered data as CSV",
        filtered.to_csv(index=False).encode("utf-8"),
        file_name=f"{meta['name'].replace(' ', '_')}_{season}_pitching.csv",
        mime="text/csv",
    )
