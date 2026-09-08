"""
Pitcher Dashboard view. Loaded via st.navigation from app.py — run the app
with `streamlit run app.py`; this file is not run directly.
"""

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import charts
import charts_pitching
import data_layer
import period_ui
import stats
import stats_pitching
import theme

ACCENT = theme.ACCENTS["pitcher"]
theme.inject_theme(ACCENT)

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
    st.subheader("Pitcher Search")

    # Player search renders first (per request), but the list of available
    # pitchers depends on season/level/pitchers-only — which render further
    # down. Read their CURRENT value from session_state before their own
    # widgets run this pass (Streamlit persists widget values across
    # reruns under their key); the fallback defaults here only matter on
    # the very first-ever render, before any of those widgets exist yet.
    level_names = list(data_layer.LEVELS.values())
    season = st.session_state.get("p_season", CURRENT_YEAR)
    picked_levels = st.session_state.get("pit_level_pills", level_names)
    picked_sport_ids = [sid for sid, name in data_layer.LEVELS.items() if name in picked_levels]
    pitchers_only = st.session_state.get("p_pitchers_only", True)

    with st.spinner("Loading player list…"):
        universe = data_layer.load_player_universe(season)

    if not universe.empty and picked_sport_ids:
        universe = universe[universe["sport_id"].isin(picked_sport_ids)]
    # Pitchers only by default — two-way players (position "TWP") stay visible too.
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
            "Pitcher", options, index=None, placeholder="Search for a pitcher…",
            format_func=lambda i: universe.loc[i, "display_name"], key="p_player"
        )
        selected_row = universe.loc[selected_idx] if selected_idx is not None else None

    season = st.number_input("Season", min_value=2015, max_value=CURRENT_YEAR,
                              value=CURRENT_YEAR, step=1, key="p_season")

    picked_levels = st.pills(
        "Levels", level_names, selection_mode="multi", default=level_names, key="pit_level_pills"
    ) or []

    pitchers_only = st.checkbox("Pitchers only (uncheck to search everyone)", value=True, key="p_pitchers_only")

    load_clicked = st.button("Load pitcher", type="primary",
                              disabled=selected_row is None, key="p_load", width='stretch')

    with st.expander("Advanced"):
        force_refresh = st.checkbox("Force refresh this pitcher's data", value=False, key="p_refresh")

# ── Load on click ─────────────────────────────────────────────────────────────
if load_clicked and selected_row is not None:
    status = st.empty()
    bar = st.empty()

    def progress(msg):
        status.info(msg)
        bar.empty()

    def game_progress(completed, total):
        status.info(f"Pulling pitch-by-pitch data — {completed} of {total} games…")
        bar.progress(completed / total if total else 0)

    df = data_layer.get_pitcher_pitch_log(
        player_id=int(selected_row["player_id"]),
        player_name=selected_row["name"],
        season=int(season),
        sport_id=int(selected_row["sport_id"]),
        force_refresh=force_refresh,
        progress_callback=progress,
        game_progress_callback=game_progress,
    )
    status.empty()
    bar.empty()

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
    theme.page_header("Pick a pitcher to get started", "", ACCENT)
    st.markdown(
        "Pick a pitcher in the sidebar and hit **Load pitcher**. Works for any MLB or "
        "minor-league pitcher (AAA) with tracked pitch-by-pitch data this season."
    )
    st.stop()

df = st.session_state.pitcher_df
meta = st.session_state.pitcher_meta
official = st.session_state.pitcher_official or {}

if df.empty and not official:
    theme.page_header(meta["name"], "No data loaded for this pitcher yet.", ACCENT, badge=meta.get("level"))
    st.stop()

is_mlb = meta["sport_id"] == 1

theme.page_header(
    meta["name"], f"{meta.get('team','') or ''} · {season} season",
    ACCENT, badge=meta.get("level"),
)

period_sel = period_ui.period_selector(
    "pit", df, unit_label="Starts",
    count_df=df[df["game_id"].isin(stats_pitching.get_pitcher_start_game_ids(df))] if not df.empty else df,
)
_start_game_ids = stats_pitching.get_pitcher_start_game_ids(df) if not df.empty else set()
df_period = stats.filter_by_period(df, period_sel["period"], period_sel["last_n_games"],
                                    period_sel["start_date"], period_sel["end_date"],
                                    restrict_to_game_ids=_start_game_ids if period_sel["period"] == "last_n" else None)
if not df.empty and df_period.empty:
    st.info("No starts in the selected period.")
    st.stop()

is_full_season = period_sel["period"] == "full"
official_for_tiles = official
if not is_full_season and not df_period.empty:
    _p_start = pd.to_datetime(df_period["game_date"]).min().date()
    _p_end = pd.to_datetime(df_period["game_date"]).max().date()
    try:
        official_for_tiles = data_layer.get_pitcher_official_season_stats(
            int(meta["player_id"]), int(season), int(meta["sport_id"]),
            start_date=_p_start, end_date=_p_end,
        )
        if not official_for_tiles:
            st.warning("Couldn't load an official line for that date range, showing full season instead.")
            official_for_tiles = official
    except Exception as e:
        st.warning(f"Couldn't load a period-scoped official line, showing full season instead: {e}")
        official_for_tiles = official

# ── Stat tiles: official line, period-scoped when a period other than Full
# Season is selected (a genuinely official date-ranged fetch, not derived
# from the pitch-level feed — see get_pitcher_official_season_stats) ────────
t1, t2, t3, t4, t5, t6 = st.columns(6)
t1.metric("ERA", f"{official_for_tiles.get('era'):.2f}" if official_for_tiles.get("era") is not None and pd.notna(official_for_tiles.get("era")) else "—")
t2.metric("WHIP", f"{official_for_tiles.get('whip'):.2f}" if official_for_tiles.get("whip") is not None and pd.notna(official_for_tiles.get("whip")) else "—")
t3.metric("W-L", f"{official_for_tiles.get('wins', '—')}-{official_for_tiles.get('losses', '—')}")
t4.metric("SV / HLD", f"{official_for_tiles.get('saves', 0)} / {official_for_tiles.get('holds', 0)}")
t5.metric("IP", official_for_tiles.get("innings_pitched_display", "—"))
t6.metric("K%", f"{official_for_tiles.get('k_pct')*100:.1f}%" if official_for_tiles.get("k_pct") is not None and pd.notna(official_for_tiles.get("k_pct")) else "—")

t7, t8, t9, t10, t11, t12 = st.columns(6)
t7.metric("BB%", f"{official_for_tiles.get('bb_pct')*100:.1f}%" if official_for_tiles.get("bb_pct") is not None and pd.notna(official_for_tiles.get("bb_pct")) else "—")
t8.metric("K/9", f"{official_for_tiles.get('k_per_9', 0):.1f}" if official_for_tiles.get("k_per_9") is not None else "—")
t9.metric("BB/9", f"{official_for_tiles.get('bb_per_9', 0):.1f}" if official_for_tiles.get("bb_per_9") is not None else "—")
t10.metric("HR/9", f"{official_for_tiles.get('hr_per_9', 0):.1f}" if official_for_tiles.get("hr_per_9") is not None else "—")
t11.metric("FIP (approx)", f"{official_for_tiles.get('fip'):.2f}" if official_for_tiles.get("fip") is not None and pd.notna(official_for_tiles.get("fip")) else "—")
t12.metric("Batters Faced", official_for_tiles.get("batters_faced", "—"))

# ── Percentile ranks (Statcast-against rows respect the period selector) ────
theme.section_title("Percentile Rankings", ACCENT)

qual_thresholds = data_layer.get_qualified_ip_thresholds(int(season), int(meta["sport_id"]))
own_ip = official_for_tiles.get("innings_pitched", 0) or 0
use_relief_pool = own_ip < qual_thresholds.get("qualified_ip_threshold", 0)

pitcher_stats_for_pct = dict(official_for_tiles)
discipline_full = stats.compute_plate_discipline(df_period) if not df_period.empty else {}
statcast_against_full = stats.compute_statcast_summary(df_period) if not df_period.empty else {}
pitcher_stats_for_pct.update({
    "whiff_pct": discipline_full.get("whiff_pct"),
    "chase_pct": discipline_full.get("chase_pct"),
    "hard_hit_pct_against": statcast_against_full.get("hard_hit_pct"),
    "avg_ev_against": statcast_against_full.get("avg_ev"),
    "sweet_spot_pct_against": statcast_against_full.get("sweet_spot_pct"),
})

pct_table = stats_pitching.build_pitching_percentile_table(
    pitcher_stats_for_pct, st.session_state.pitching_standard_pool,
    st.session_state.pitching_savant_pool, is_mlb, use_relief_pool=use_relief_pool,
)
st.plotly_chart(charts.percentile_bars(pct_table), width='stretch')
if is_mlb:
    st.caption("Whiff% (induced)/Chase% (induced) percentiles aren't available right now — they come from "
               "Baseball Savant's \"Swing & Take\" leaderboard specifically, which is currently broken on "
               "Savant's own end (independently confirmed via another actively-maintained tool that depends "
               "on the same data). Their values above are still your own real numbers, computed directly "
               "from this pitcher's pitch-level data — just without a league percentile to compare against "
               "for now.")

with st.expander("Data source status (debug info)"):
    st.download_button(
        "Download full raw pitch log (CSV) — attach this to a chat message if something still looks off",
        df.to_csv(index=False).encode("utf-8") if not df.empty else b"",
        file_name=f"{meta['name'].replace(' ', '_')}_{season}_raw_pitch_log.csv",
        mime="text/csv",
        width='stretch',
        disabled=df.empty,
    )

    orphan_check = stats.compute_orphaned_at_bats(df)
    if orphan_check["n_orphaned"] > 0:
        st.error(
            f"**{orphan_check['n_orphaned']} of {orphan_check['n_total_at_bats']} at-bats are missing an "
            f"outcome** (pitch rows exist, but none carry the actual result). This won't affect the ERA/WHIP/"
            f"W-L tiles (those come straight from MLB's official stats), but it will affect the Statcast-"
            f"against percentiles and the Contact Allowed/Splits tabs below, which are derived from this "
            f"pitcher's own pulled pitch log."
        )
        st.dataframe(pd.DataFrame(orphan_check["orphaned_examples"]), width='stretch', hide_index=True)
    else:
        st.write(f"**Plate-appearance completeness:** all {orphan_check['n_total_at_bats']} at-bats faced "
                 f"have a recorded outcome — no dropped plate appearances detected in this pitcher's pulled data.")

    completeness = stats.compute_data_completeness_summary(df)
    if completeness["excluded_event_counts"]:
        st.write("**Excluded from batters-faced/opponent-AVG** (baserunning/administrative outcomes, not a "
                 "real batting result):")
        excl_df = pd.DataFrame(
            sorted(completeness["excluded_event_counts"].items(), key=lambda kv: -kv[1]),
            columns=["event_type", "count"],
        )
        st.dataframe(excl_df, width='stretch', hide_index=True, height=min(200, 40 + 28 * len(excl_df)))

    dup_check = stats.compute_duplicate_at_bats(df)
    if dup_check["n_duplicated"] > 0:
        st.error(
            f"**{dup_check['n_duplicated']} of {dup_check['n_total_at_bats']} at-bats have MORE than one "
            f"recorded outcome** — being double-counted, inflating the pitch-log-derived numbers above."
        )
        st.dataframe(pd.DataFrame(dup_check["duplicate_examples"]), width='stretch', hide_index=True)
    else:
        st.write("**Duplicate check:** no at-bat has more than one recorded outcome — "
                 "no double-counted plate appearances detected in this pitcher's pulled data.")

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
    if use_relief_pool:
        st.caption(f"Using the relief-eligible pool ({qual_thresholds.get('relief_ip_floor', 0):.0f}+ IP) since "
                   f"this pitcher's IP ({own_ip:.1f}) is below the official qualified threshold "
                   f"({qual_thresholds.get('qualified_ip_threshold', 0):.0f} IP).")
    st.dataframe(pct_table, width='stretch', hide_index=True)

st.divider()

# ── Filters (apply to the tabs below only) ────────────────────────────────────
pitch_options = sorted(df_period["pitch_description"].dropna().unique().tolist()) if not df_period.empty else []
if pitch_options:
    picked_pitches = st.pills(
        "Pitch types", pitch_options, selection_mode="multi", default=pitch_options,
        format_func=stats.shorten_pitch, key="pit_pitch_pills",
    ) or []
else:
    picked_pitches = []

filt_col1, filt_col2 = st.columns(2)
with filt_col1:
    hand_filter = st.radio("Batter hand", ["Both", "vs LHH", "vs RHH"], horizontal=True)
with filt_col2:
    if not df_period.empty and "is_home" in df_period.columns and df_period["is_home"].notna().any():
        loc_filter = st.radio("Location", ["Both", "Home", "Away"], horizontal=True)
    else:
        loc_filter = "Both"

if not df_period.empty:
    filtered = df_period[df_period["pitch_description"].isin(picked_pitches)] if picked_pitches else df_period.iloc[0:0]
    if hand_filter == "vs LHH":
        filtered = filtered[filtered["batter_hand"] == "L"]
    elif hand_filter == "vs RHH":
        filtered = filtered[filtered["batter_hand"] == "R"]
    if loc_filter == "Home":
        filtered = filtered[filtered["is_home"] == True]  # noqa: E712
    elif loc_filter == "Away":
        filtered = filtered[filtered["is_home"] == False]  # noqa: E712
else:
    filtered = df_period

if filtered.empty:
    st.info("No pitch-level data for the current filter selection.")
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
    trend_col1, trend_col2 = st.columns([1, 2])
    with trend_col1:
        roll_window = st.slider("Rolling window (PA)", min_value=10, max_value=75, value=25, step=5)
    with trend_col2:
        selected_trend_stats = st.multiselect(
            "Stats to show (up to 3)", stats_pitching.PITCHER_TREND_STAT_OPTIONS,
            default=["AVG Against", "Whiff% Induced"], max_selections=3, key="pit_trend_stats",
        )
    if selected_trend_stats:
        trend_df = stats_pitching.compute_pitcher_multi_rolling_trend(
            df_period, window=roll_window, stat_names=selected_trend_stats
        )
        st.plotly_chart(
            charts.multi_rolling_trend_chart(
                trend_df, selected_trend_stats, roll_window,
                format_map=stats_pitching.PITCHER_TREND_STAT_FORMAT,
            ),
            width='stretch',
        )
    else:
        st.info("Pick at least one stat above to see a trend.")

with tab_splits:
    splits = stats_pitching.compute_pitcher_splits(df_period)
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
    st.dataframe(filtered, width='stretch', height=500)
    st.download_button(
        "Download filtered data as CSV",
        filtered.to_csv(index=False).encode("utf-8"),
        file_name=f"{meta['name'].replace(' ', '_')}_{season}_pitching.csv",
        mime="text/csv",
    )
