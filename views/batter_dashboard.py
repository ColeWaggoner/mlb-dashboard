"""
Batter Dashboard view. Loaded via st.navigation from app.py — run the app
with `streamlit run app.py`; this file is not run directly.

Search any batter across MLB or the full-season affiliated minors (AAA),
see their slash line, Statcast-quality batted-ball
metrics, a pitch-type-filterable spray chart, plate discipline, and
percentile ranks against qualified hitters at their level.
"""

from datetime import date
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import charts
import data_layer
import period_ui
import stats
import theme

ACCENT = theme.ACCENTS["batter"]
theme.inject_theme(ACCENT)

CURRENT_YEAR = date.today().year

# ── Session state ────────────────────────────────────────────────────────────
for key, default in [
    ("player_df", None), ("player_meta", None), ("standard_pool", None),
    ("savant_pool", None), ("loaded_key", None),
]:
    st.session_state.setdefault(key, default)


def fmt_rate(x, allow_negative=False):
    """Formats a rate stat as .xxx (or -.xxx), rounding to the nearest
    thousandth like a real box score."""
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


# ── Sidebar: player search ───────────────────────────────────────────────────
with st.sidebar:
    st.subheader("Batter Search")

    # Player search renders first (per request), but the list of available
    # players depends on season/level — which are rendered further down.
    # Read their CURRENT value from session_state before their own widgets
    # run this pass (Streamlit persists widget values across reruns under
    # their key, so this reflects whatever was last picked); the fallback
    # defaults here only matter on the very first-ever render, before
    # either widget has been instantiated at all.
    level_names = list(data_layer.LEVELS.values())
    season = st.session_state.get("bat_season", CURRENT_YEAR)
    picked_levels = st.session_state.get("bat_level_pills", level_names)
    picked_sport_ids = [sid for sid, name in data_layer.LEVELS.items() if name in picked_levels]

    with st.spinner("Loading player list…"):
        universe = data_layer.load_player_universe(season)

    if not universe.empty and picked_sport_ids:
        universe = universe[universe["sport_id"].isin(picked_sport_ids)]

    if universe.empty:
        st.warning("No player list loaded yet — this needs network access to "
                    "statsapi.mlb.com, so it only works when you run the app "
                    "locally, not in a sandboxed preview.")
        selected_row = None
    else:
        universe = universe.sort_values("name")
        options = universe.index.tolist()
        selected_idx = st.selectbox(
            "Player",
            options,
            index=None,
            placeholder="Search for a batter…",
            format_func=lambda i: universe.loc[i, "display_name"],
        )
        selected_row = universe.loc[selected_idx] if selected_idx is not None else None

    season = st.number_input("Season", min_value=2015, max_value=CURRENT_YEAR,
                              value=CURRENT_YEAR, step=1, key="bat_season")

    picked_levels = st.pills(
        "Levels", level_names, selection_mode="multi", default=level_names, key="bat_level_pills"
    ) or []

    load_clicked = st.button("Load batter", type="primary", width='stretch',
                              disabled=selected_row is None)

    with st.expander("Advanced"):
        force_refresh = st.checkbox("Force refresh this player's data", value=False)
        if st.button("Refresh player list", width='stretch'):
            with st.spinner("Pulling rosters…"):
                data_layer.load_player_universe(season, force_refresh=True)

# ── Load data on click ────────────────────────────────────────────────────────
if load_clicked and selected_row is not None:
    key = (selected_row["player_id"], season, selected_row["sport_id"])
    status = st.empty()

    def progress(msg):
        status.info(msg)

    df = data_layer.get_batter_pitch_log(
        player_id=int(selected_row["player_id"]),
        player_name=selected_row["name"],
        season=int(season),
        sport_id=int(selected_row["sport_id"]),
        force_refresh=force_refresh,
        progress_callback=progress,
    )
    status.empty()

    if df.empty:
        st.warning(f"No plate-appearance data found for {selected_row['name']} in {season} "
                    f"at {selected_row['level']}. They may not have played yet, or this level's "
                    f"game feed doesn't carry pitch-level data.")
    else:
        df = data_layer.attach_home_away(df, int(season), int(selected_row["sport_id"]))
        batter_hand = df["batter_hand"].dropna().iloc[0] if df["batter_hand"].notna().any() else "R"
        df = stats.enrich_spray_coordinates(df, batter_hand=batter_hand)

    st.session_state.player_df = df
    st.session_state.player_meta = selected_row.to_dict()
    st.session_state.loaded_key = key

    with st.spinner("Loading league baselines for percentile ranks…"):
        try:
            st.session_state.standard_pool = data_layer.get_standard_leaderboard(
                int(season), int(selected_row["sport_id"])
            )
        except Exception as e:
            st.session_state.standard_pool = pd.DataFrame()
            st.warning(f"Couldn't load the league leaderboard for standard-stat percentiles: {e}")
        if selected_row["sport_id"] == 1:
            try:
                st.session_state.savant_pool = data_layer.get_savant_percentile_pool(int(season))
            except Exception as e:
                st.session_state.savant_pool = pd.DataFrame()
                st.warning(f"Couldn't load Baseball Savant's leaderboard for Statcast percentiles: {e}")
        else:
            st.session_state.savant_pool = pd.DataFrame()


# ── Main content ──────────────────────────────────────────────────────────────
if st.session_state.player_df is None:
    theme.page_header("Pick a batter to get started", "", ACCENT)
    st.markdown(
        "Pick a player in the sidebar and hit **Load batter**. Works for any MLB or "
        "minor-league hitter (AAA) with tracked pitch-by-pitch data this season."
    )
    st.stop()

df = st.session_state.player_df
meta = st.session_state.player_meta

if df.empty:
    theme.page_header(meta["name"], "No data loaded for this player yet.", ACCENT, badge=meta.get("level"))
    st.stop()

is_mlb = meta["sport_id"] == 1

theme.page_header(
    meta["name"], f"{meta.get('team','') or ''} · {meta.get('position','')} · {season} season",
    ACCENT, badge=meta.get("level"),
)

period_sel = period_ui.period_selector("bat", df)
df_period = stats.filter_by_period(df, period_sel["period"], period_sel["last_n_games"],
                                    period_sel["start_date"], period_sel["end_date"])

if df_period.empty:
    st.info("No games in the selected period.")
    st.stop()

# ── Stat tiles (selected period) ─────────────────────────────────────────────
_orphan_precheck = stats.compute_orphaned_at_bats(df)
if _orphan_precheck["n_orphaned"] > 0:
    st.warning(
        f"{_orphan_precheck['n_orphaned']} of {_orphan_precheck['n_total_at_bats']} at-bats this season are "
        f"missing a recorded outcome, which will make the stats below come in lower than official sources. "
        f"See the Data source status expander below for detail."
    )

_dup_precheck = stats.compute_duplicate_at_bats(df)
if _dup_precheck["n_duplicated"] > 0:
    st.warning(
        f"{_dup_precheck['n_duplicated']} of {_dup_precheck['n_total_at_bats']} at-bats this season have "
        f"MORE than one recorded outcome, which will make PA/AB and counting stats come in higher than "
        f"official sources. See the Data source status expander below for detail."
    )

slash = stats.compute_slash_line(df_period)
statcast = stats.compute_statcast_summary(df_period)
discipline = stats.compute_plate_discipline(df_period)

t1, t2, t3, t4, t5, t6 = st.columns(6)
t1.metric("AVG", fmt_rate(slash["ba"]))
t2.metric("OBP", fmt_rate(slash["obp"]))
t3.metric("SLG", fmt_rate(slash["slg"]))
t4.metric("OPS", f"{slash['ops']:.3f}" if pd.notna(slash["ops"]) else "—")
t5.metric("K%", f"{slash['k_pct']*100:.1f}%" if pd.notna(slash["k_pct"]) else "—")
t6.metric("BB%", f"{slash['bb_pct']*100:.1f}%" if pd.notna(slash["bb_pct"]) else "—")

t7, t8, t9, t10, t11, t12 = st.columns(6)
t7.metric("Hard-Hit%", f"{statcast['hard_hit_pct']*100:.1f}%" if pd.notna(statcast["hard_hit_pct"]) else "—")
t8.metric("Avg Exit Velo", f"{statcast['avg_ev']:.1f} mph" if pd.notna(statcast["avg_ev"]) else "—")
t9.metric("Sweet-Spot%", f"{statcast['sweet_spot_pct']*100:.1f}%" if pd.notna(statcast["sweet_spot_pct"]) else "—")
t10.metric("Chase%", f"{discipline['chase_pct']*100:.1f}%" if pd.notna(discipline["chase_pct"]) else "—")
t11.metric("Whiff%", f"{discipline['whiff_pct']*100:.1f}%" if pd.notna(discipline["whiff_pct"]) else "—")
t12.metric("ISO", fmt_rate(slash["iso"], allow_negative=True))

theme.compact_stat_row([
    ("PA", slash["n_pa"]), ("AB", slash["n_ab"]), ("H", slash["n_hits"]),
    ("2B", slash["n_2b"]), ("3B", slash["n_3b"]), ("HR", slash["n_hr"]),
    ("RBI", slash["n_rbi"]), ("BB", slash["n_bb"]), ("SO", slash["n_k"]), ("HBP", slash["n_hbp"]),
])

# ── Percentile ranks ──────────────────────────────────────────────────────────
theme.section_title("Percentile Rankings", ACCENT)

is_full_season = period_sel["period"] == "full"
compare_mode = "Full-Season League"
if not is_full_season:
    compare_mode = st.radio(
        "Compare against", ["Full-Season League", "Same-Period League"],
        horizontal=True, key="bat_compare_mode",
    )

standard_pool_for_pct = st.session_state.standard_pool
savant_pool_for_pct = st.session_state.savant_pool
period_pool_note = None

if compare_mode == "Same-Period League" and not is_full_season:
    period_start = pd.to_datetime(df_period["game_date"]).min().date()
    period_end = pd.to_datetime(df_period["game_date"]).max().date()
    try:
        standard_pool_for_pct = data_layer.get_standard_leaderboard(
            int(season), int(meta["sport_id"]), start_date=period_start, end_date=period_end,
        )
    except Exception as e:
        st.warning(f"Couldn't load a period-scoped league comparison, falling back to full season: {e}")
        standard_pool_for_pct = st.session_state.standard_pool
    period_pool_note = (
        f"AVG/OBP/SLG/OPS/K%/BB% below compare against other qualified hitters' totals over "
        f"{period_start} to {period_end} too. Hard-Hit%/Exit Velo/Sweet-Spot% still "
        f"compare against the full-season Baseball Savant pool — a same-period version of that "
        f"leaderboard isn't available. Chase%/Whiff% don't have a percentile comparison at all "
        f"right now — see the note below the percentile chart."
    )
    # Directly checkable proof the toggle actually did something: if these
    # two pools have the same mean AVG, the date-scoped fetch isn't
    # returning different data and the toggle is a no-op regardless of what
    # the UI shows.
    _season_pool = st.session_state.standard_pool
    if _season_pool is not None and not _season_pool.empty and not standard_pool_for_pct.empty:
        _season_mean = _season_pool["avg"].mean()
        _period_mean = standard_pool_for_pct["avg"].mean()
        _same = abs(_season_mean - _period_mean) < 1e-6
        (st.error if _same else st.success)(
            f"Season-long pool mean AVG: {_season_mean:.3f} ({len(_season_pool)} players) "
            f"vs. period-scoped pool mean AVG: {_period_mean:.3f} ({len(standard_pool_for_pct)} players)."
            + (" These are identical — the date-scoped fetch is not returning different data, so this toggle "
               "isn't actually changing anything yet." if _same else " These differ, confirming the toggle is "
               "pulling genuinely different data.")
        )

combined_stats = {**slash, **statcast, **discipline}
pct_table = stats.build_percentile_table(
    combined_stats, standard_pool_for_pct, savant_pool_for_pct, is_mlb,
)
st.plotly_chart(charts.percentile_bars(pct_table), width='stretch')
if is_mlb:
    st.caption("Chase%/Whiff% percentiles aren't available right now — they come from Baseball Savant's "
               "\"Swing & Take\" leaderboard specifically, which is currently broken on Savant's own end "
               "(independently confirmed via another actively-maintained tool that depends on the same "
               "data). Their values above are still your own real numbers, computed directly from this "
               "player's pitch-level data — just without a league percentile to compare against for now.")
if period_pool_note:
    st.caption(period_pool_note)

with st.expander("Data source status (debug info)"):
    st.download_button(
        "Download full raw pitch log (CSV) — attach this to a chat message if something still looks off",
        df.to_csv(index=False).encode("utf-8"),
        file_name=f"{meta['name'].replace(' ', '_')}_{season}_raw_pitch_log.csv",
        mime="text/csv",
        width='stretch',
    )
    st.caption("This is every pitch/plate-appearance row for the full season, unfiltered — the exact data "
               "everything on this page is computed from. If a stat still looks wrong, downloading this and "
               "attaching it to a message is the fastest way to get it debugged directly instead of guessing "
               "from the summary numbers alone.")

    completeness = stats.compute_data_completeness_summary(df)
    st.write(f"**Games pulled:** {completeness['n_games']}  ·  **Plate appearances:** {completeness['n_pa']} "
             f"(after excluding non-batting outcomes — {completeness['n_pa_raw']} raw rows before that)  ·  "
             f"**Date range:** {completeness['date_min']} to {completeness['date_max']}")
    st.caption("Compare 'Plate appearances' directly against an official source's PA count. If 'Games pulled' "
               "is short of the official games-played number, get_player_games_list didn't return every game "
               "for this player — a different failure mode than a plate appearance being miscounted within a "
               "game that DID get pulled correctly.")
    if completeness["excluded_event_counts"]:
        st.write("**Excluded from PA/AB** (baserunning/administrative outcomes attached to a batter's at-bat "
                 "entry, not a real batting result):")
        excl_df = pd.DataFrame(
            sorted(completeness["excluded_event_counts"].items(), key=lambda kv: -kv[1]),
            columns=["event_type", "count"],
        )
        st.dataframe(excl_df, width='stretch', hide_index=True, height=min(200, 40 + 28 * len(excl_df)))
    if completeness["event_type_counts"]:
        st.write("**Full raw event_type breakdown** (everything pulled, before any exclusion):")
        event_df = pd.DataFrame(
            sorted(completeness["event_type_counts"].items(), key=lambda kv: -kv[1]),
            columns=["event_type", "count"],
        )
        st.dataframe(event_df, width='stretch', hide_index=True, height=min(300, 40 + 28 * len(event_df)))

    orphan_check = stats.compute_orphaned_at_bats(df)
    if orphan_check["n_orphaned"] > 0:
        st.error(
            f"**{orphan_check['n_orphaned']} of {orphan_check['n_total_at_bats']} at-bats are missing an "
            f"outcome** (pitch rows exist, but none carry the actual result). If you're seeing this after "
            f"pulling fresh data with the get_data_df fix in place, that fix isn't fully covering what's "
            f"happening here — share this list and I can dig further."
        )
        st.dataframe(pd.DataFrame(orphan_check["orphaned_examples"]), width='stretch', hide_index=True)
    else:
        st.write(f"**Plate-appearance completeness:** all {orphan_check['n_total_at_bats']} at-bats have a "
                 f"recorded outcome — no dropped plate appearances detected in this player's pulled data.")

    dup_check = stats.compute_duplicate_at_bats(df)
    if dup_check["n_duplicated"] > 0:
        st.error(
            f"**{dup_check['n_duplicated']} of {dup_check['n_total_at_bats']} at-bats have MORE than one "
            f"recorded outcome** — this at-bat is being counted more than once, inflating PA/AB/counting "
            f"stats above official sources. If you're seeing this after pulling fresh data with the game-id "
            f"dedup fix in place, that fix isn't fully covering what's happening here — share this list."
        )
        st.dataframe(pd.DataFrame(dup_check["duplicate_examples"]), width='stretch', hide_index=True)
    else:
        st.write(f"**Duplicate check:** no at-bat has more than one recorded outcome — "
                 f"no double-counted plate appearances detected in this player's pulled data.")

    std_pool = standard_pool_for_pct
    sav_pool = st.session_state.savant_pool

    if std_pool is None or std_pool.empty:
        std_summary = "not loaded"
    else:
        n_qualified = int(std_pool["qualified"].sum())
        std_summary = f"{len(std_pool)} players, {n_qualified} qualified"
    st.write(f"**Standard leaderboard (MLB Stats API):** {std_summary}")
    if std_pool is not None and not std_pool.empty:
        st.caption(f"Columns: {list(std_pool.columns)}")

    sav_summary = "not loaded" if sav_pool is None or sav_pool.empty else f"{len(sav_pool)} players"
    st.write(f"**Baseball Savant leaderboard (MLB only):** {sav_summary}")
    if sav_pool is not None and not sav_pool.empty:
        st.caption(f"Columns: {list(sav_pool.columns)}")

    st.dataframe(pct_table, width='stretch', hide_index=True)

st.divider()

# ── Filters (apply to the tabs below only) ────────────────────────────────────
pitch_options = sorted(df_period["pitch_description"].dropna().unique().tolist())
if pitch_options:
    picked_pitches = st.pills(
        "Pitch types", pitch_options, selection_mode="multi", default=pitch_options,
        format_func=stats.shorten_pitch, key="bat_pitch_pills",
    ) or []
else:
    picked_pitches = []

filt_col1, filt_col2 = st.columns(2)
with filt_col1:
    hand_filter = st.radio("Pitcher hand", ["Both", "vs LHP", "vs RHP"], horizontal=True)
with filt_col2:
    if "is_home" in df_period.columns and df_period["is_home"].notna().any():
        loc_filter = st.radio("Location", ["Both", "Home", "Away"], horizontal=True)
    else:
        loc_filter = "Both"

filtered = df_period[df_period["pitch_description"].isin(picked_pitches)] if picked_pitches else df_period.iloc[0:0]
if hand_filter == "vs LHP":
    filtered = filtered[filtered["pitcher_hand"] == "L"]
elif hand_filter == "vs RHP":
    filtered = filtered[filtered["pitcher_hand"] == "R"]
if loc_filter == "Home":
    filtered = filtered[filtered["is_home"] == True]  # noqa: E712
elif loc_filter == "Away":
    filtered = filtered[filtered["is_home"] == False]  # noqa: E712

# ── Tabs for the deep-dive views ──────────────────────────────────────────────
tab_spray, tab_pitches, tab_discipline, tab_batted, tab_trend, tab_splits, tab_raw = st.tabs(
    ["Spray & Zone", "Pitch Mix", "Plate Discipline", "Batted Ball", "Trends", "Splits", "Raw Data"]
)

with tab_spray:
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(charts.spray_chart(filtered), width='stretch')
    with c2:
        st.plotly_chart(charts.zone_chart(filtered), width='stretch')

with tab_pitches:
    pitch_table = stats.compute_pitch_type_table(filtered)
    c1, c2 = st.columns([1, 1.3])
    with c1:
        st.plotly_chart(charts.pitch_mix_chart(pitch_table), width='stretch')
    with c2:
        st.markdown("**Batting stats by pitch type**")
        if not pitch_table.empty:
            display_cols = ["pitch_type", "pa", "ab", "ba", "obp", "slg", "ops", "k_pct", "bb_pct"]
            show = pitch_table[display_cols].copy()
            for c in ["ba", "obp", "slg", "ops"]:
                show[c] = show[c].map(lambda v: f"{v:.3f}" if pd.notna(v) else "—")
            for c in ["k_pct", "bb_pct"]:
                show[c] = show[c].map(lambda v: f"{v:.0f}%" if pd.notna(v) else "—")
            show.columns = ["Pitch", "PA", "AB", "BA", "OBP", "SLG", "OPS", "K%", "BB%"]
            st.dataframe(show, width='stretch', hide_index=True)
        else:
            st.info("No pitch-type data for this filter.")

with tab_discipline:
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(charts.discipline_heatmap(filtered), width='stretch')
    with c2:
        swing_grid, contact_grid, count_n = stats.compute_count_matrix(filtered)
        detail_all = stats.compute_count_cell_detail(filtered)
        st.plotly_chart(
            charts.count_heatmap(contact_grid, count_n, label="Contact%", title="Contact Rate by Count",
                                  hover_detail=detail_all),
            width='stretch',
        )

    contact_profile = stats.compute_contact_profile(filtered)
    st.plotly_chart(charts.contact_profile_chart(contact_profile), width='stretch')

    st.markdown("**Contact Rate by Count — In Zone vs. Out of Zone**")
    iz_contact_grid, iz_swing_n, oz_contact_grid, oz_swing_n = stats.compute_contact_rate_matrix_by_zone(filtered)
    detail_iz = stats.compute_count_cell_detail(filtered, zone_filter="in")
    detail_oz = stats.compute_count_cell_detail(filtered, zone_filter="out")
    c3, c4 = st.columns(2)
    with c3:
        st.plotly_chart(
            charts.count_heatmap(iz_contact_grid, iz_swing_n, label="Contact%", title="In-Zone Contact Rate by Count",
                                  hover_detail=detail_iz),
            width='stretch',
        )
    with c4:
        st.plotly_chart(
            charts.count_heatmap(oz_contact_grid, oz_swing_n, label="Contact%",
                                  title="Out-of-Zone (Chase) Contact Rate by Count", hover_detail=detail_oz),
            width='stretch',
        )

    d1, d2, d3, d4, d5 = st.columns(5)
    filtered_discipline = stats.compute_plate_discipline(filtered)
    d1.metric("Zone%", f"{filtered_discipline['zone_pct']*100:.1f}%" if pd.notna(filtered_discipline["zone_pct"]) else "—")
    d2.metric("Z-Swing%", f"{filtered_discipline['z_swing_pct']*100:.1f}%" if pd.notna(filtered_discipline["z_swing_pct"]) else "—")
    d3.metric("Contact%", f"{filtered_discipline['contact_pct']*100:.1f}%" if pd.notna(filtered_discipline["contact_pct"]) else "—")
    d4.metric("CSW%", f"{filtered_discipline['csw_pct']*100:.1f}%" if pd.notna(filtered_discipline["csw_pct"]) else "—")
    d5.metric("1st-Pitch Strike%", f"{filtered_discipline['first_pitch_strike_pct']*100:.1f}%"
              if pd.notna(filtered_discipline["first_pitch_strike_pct"]) else "—")

with tab_batted:
    bb_profile = stats.compute_batted_ball_profile(filtered)
    c1, c2 = st.columns([1, 1])
    with c1:
        st.plotly_chart(charts.ev_la_scatter(filtered), width='stretch')
    with c2:
        st.markdown("**Batted-ball profile**")
        b1, b2, b3, b4 = st.columns(4)
        b1.metric("GB%", f"{bb_profile['gb_pct']*100:.0f}%" if pd.notna(bb_profile["gb_pct"]) else "—")
        b2.metric("FB%", f"{bb_profile['fb_pct']*100:.0f}%" if pd.notna(bb_profile["fb_pct"]) else "—")
        b3.metric("LD%", f"{bb_profile['ld_pct']*100:.0f}%" if pd.notna(bb_profile["ld_pct"]) else "—")
        b4.metric("PU%", f"{bb_profile['pu_pct']*100:.0f}%" if pd.notna(bb_profile["pu_pct"]) else "—")
        b5, b6, b7 = st.columns(3)
        b5.metric("Pull%", f"{bb_profile['pull_pct']*100:.0f}%" if pd.notna(bb_profile["pull_pct"]) else "—")
        b6.metric("Cent%", f"{bb_profile['cent_pct']*100:.0f}%" if pd.notna(bb_profile["cent_pct"]) else "—")
        b7.metric("Oppo%", f"{bb_profile['oppo_pct']*100:.0f}%" if pd.notna(bb_profile["oppo_pct"]) else "—")

with tab_trend:
    trend_col1, trend_col2 = st.columns([1, 2])
    with trend_col1:
        roll_window = st.slider("Rolling window (PA)", min_value=10, max_value=75, value=25, step=5)
    with trend_col2:
        selected_trend_stats = st.multiselect(
            "Stats to show (up to 3)", stats.TREND_STAT_OPTIONS, default=["AVG", "OPS"],
            max_selections=3, key="bat_trend_stats",
        )
    if selected_trend_stats:
        trend_df = stats.compute_multi_rolling_trend(df_period, window=roll_window, stat_names=selected_trend_stats)
        st.plotly_chart(charts.multi_rolling_trend_chart(trend_df, selected_trend_stats, roll_window), width='stretch')
    else:
        st.info("Pick at least one stat above to see a trend.")

with tab_splits:
    splits = stats.compute_splits(df_period)
    if not splits:
        st.info("Not enough data to compute splits.")
    else:
        rows = []
        for label, s in splits.items():
            rows.append({
                "Split": label, "PA": s["n_pa"], "AB": s["n_ab"],
                "AVG": f"{s['ba']:.3f}" if pd.notna(s["ba"]) else "—",
                "OBP": f"{s['obp']:.3f}" if pd.notna(s["obp"]) else "—",
                "SLG": f"{s['slg']:.3f}" if pd.notna(s["slg"]) else "—",
                "OPS": f"{s['ops']:.3f}" if pd.notna(s["ops"]) else "—",
                "K%": f"{s['k_pct']*100:.1f}%" if pd.notna(s["k_pct"]) else "—",
                "BB%": f"{s['bb_pct']*100:.1f}%" if pd.notna(s["bb_pct"]) else "—",
            })
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

with tab_raw:
    st.dataframe(filtered, width='stretch', height=500)
    st.download_button(
        "Download filtered data as CSV",
        filtered.to_csv(index=False).encode("utf-8"),
        file_name=f"{meta['name'].replace(' ', '_')}_{season}_pitches.csv",
        mime="text/csv",
    )
