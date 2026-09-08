"""
Team Dashboard — third page of the app. Deliberately built from bulk
team-level endpoints (one request covers every team) rather than pulling
every player's pitch log, so it loads fast even though a team has 25+
players. No pitch-level charts here on purpose (spray/zone/movement don't
mean much averaged across a whole roster) — this is stat lines, rankings,
and roster leaderboards.
"""

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import charts
import data_layer
import period_ui
import stats
import stats_team
import theme

theme.inject_theme(theme.ACCENTS["team"])

CURRENT_YEAR = date.today().year
ACCENT = theme.ACCENTS["team"]

for key, default in [
    ("team_meta", None), ("team_hitting_pool", None), ("team_pitching_pool", None),
    ("team_hitters_roster", None), ("team_pitchers_roster", None),
    ("team_savant_batting_pool", None), ("team_savant_pitching_pool", None),
    ("team_pitch_log", None),
]:
    st.session_state.setdefault(key, default)


def fmt_rate(x, allow_negative=False, decimals=3):
    if x is None or pd.isna(x):
        return "—"
    if x < 0 and not allow_negative:
        return "—"
    s = f"{x:.{decimals}f}"
    if decimals == 3:
        if s.startswith("0."):
            return s[1:]
        if s.startswith("-0."):
            return "-" + s[2:]
    return s


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("Team Search")

    # Team search renders first (per request), but the list of available
    # teams depends on season/level — which render further down. Read
    # their CURRENT value from session_state before their own widgets run
    # this pass (Streamlit persists widget values across reruns under
    # their key); the fallback defaults here only matter on the very
    # first-ever render, before either widget has been instantiated yet.
    level_names = list(data_layer.LEVELS.values())
    season = st.session_state.get("t_season", CURRENT_YEAR)
    picked_level = st.session_state.get("t_level", level_names[0])
    sport_id = [sid for sid, name in data_layer.LEVELS.items() if name == picked_level][0]

    with st.spinner("Loading team list…"):
        teams = data_layer.get_team_list(int(season), sport_id)

    if teams.empty:
        st.warning("No team list loaded yet — this needs network access to "
                    "statsapi.mlb.com, so it only works when you run the app "
                    "locally, not in a sandboxed preview.")
        selected_team = None
    else:
        team_names = teams["name"].tolist()
        selected_team = st.selectbox("Team", team_names, index=None, placeholder="Search for a team…", key="t_team")

    season = st.number_input("Season", min_value=2015, max_value=CURRENT_YEAR, value=CURRENT_YEAR, step=1, key="t_season")

    picked_level = st.pills(
        "Level", level_names, selection_mode="single", default=level_names[0], required=True, key="t_level"
    )

    load_clicked = st.button("Load team", type="primary", disabled=selected_team is None,
                              key="t_load", width="stretch")

    with st.expander("Advanced"):
        force_refresh = st.checkbox("Force refresh league data", value=False, key="t_refresh")

# ── Load on click ─────────────────────────────────────────────────────────────
if load_clicked and selected_team is not None:
    team_row = teams[teams["name"] == selected_team].iloc[0]
    st.session_state.team_meta = {
        "team_id": int(team_row["team_id"]), "name": selected_team,
        "abbreviation": team_row.get("abbreviation"), "league_name": team_row.get("league_name"),
        "level": picked_level, "sport_id": sport_id,
    }
    st.session_state.team_pitch_log = None  # a newly selected team invalidates any previously loaded deep-dive data

    with st.spinner("Loading team and league hitting/pitching stats…"):
        try:
            st.session_state.team_hitting_pool = data_layer.get_team_hitting_leaderboard(
                int(season), sport_id, force_refresh=force_refresh
            )
        except Exception as e:
            st.session_state.team_hitting_pool = pd.DataFrame()
            st.warning(f"Couldn't load team hitting leaderboard: {e}")

        try:
            st.session_state.team_pitching_pool = data_layer.get_team_pitching_leaderboard(
                int(season), sport_id, force_refresh=force_refresh
            )
        except Exception as e:
            st.session_state.team_pitching_pool = pd.DataFrame()
            st.warning(f"Couldn't load team pitching leaderboard: {e}")

        try:
            st.session_state.team_hitters_roster = data_layer.get_standard_leaderboard(
                int(season), sport_id, force_refresh=force_refresh
            )
        except Exception as e:
            st.session_state.team_hitters_roster = pd.DataFrame()

        try:
            st.session_state.team_pitchers_roster = data_layer.get_pitching_standard_leaderboard(
                int(season), sport_id, force_refresh=force_refresh
            )
        except Exception as e:
            st.session_state.team_pitchers_roster = pd.DataFrame()

        if sport_id == 1:
            try:
                st.session_state.team_savant_batting_pool = data_layer.get_savant_percentile_pool(int(season))
            except Exception:
                st.session_state.team_savant_batting_pool = pd.DataFrame()
            try:
                st.session_state.team_savant_pitching_pool = data_layer.get_pitching_savant_percentile_pool(int(season))
            except Exception:
                st.session_state.team_savant_pitching_pool = pd.DataFrame()
        else:
            st.session_state.team_savant_batting_pool = pd.DataFrame()
            st.session_state.team_savant_pitching_pool = pd.DataFrame()

# ── Main content ──────────────────────────────────────────────────────────────
if st.session_state.team_meta is None:
    theme.page_header("Pick a team to get started", "", ACCENT)
    st.markdown(
        "Pick a level and team in the sidebar and hit **Load team**. Covers full-season "
        "hitting and pitching performance, how the team ranks against the rest of the "
        "league, and every player's own line."
    )
    st.stop()

meta = st.session_state.team_meta
_season_hitting_pool = st.session_state.team_hitting_pool
_season_pitching_pool = st.session_state.team_pitching_pool
is_mlb = meta["sport_id"] == 1

if (_season_hitting_pool is None or _season_hitting_pool.empty) and (_season_pitching_pool is None or _season_pitching_pool.empty):
    theme.page_header(meta["name"], meta.get("league_name") or "", ACCENT, badge=meta["level"])
    st.info("No team stats loaded — see the warnings above for why, or try Force refresh.")
    st.stop()

theme.page_header(meta["name"], f"{meta.get('league_name','')} · {season} season", ACCENT, badge=meta["level"])

# ── Period selector — one control for the whole page, including the Deep
# Dive section below (which reuses this same selection rather than having
# its own separate widget). "Last N Games" is translated into a date range
# via this team's own schedule, then that date range is used to re-fetch
# period-scoped versions of the bulk hitting/pitching/roster leaderboards
# below — those are genuinely different data for that window, not just the
# full-season numbers relabeled. ──────────────────────────────────────────
_sched = data_layer.get_schedule_lookup(int(season), meta["sport_id"])
_team_games = pd.DataFrame(columns=["game_id", "game_date"])
if not _sched.empty:
    _team_games = _sched[(_sched["home_id"] == meta["team_id"]) | (_sched["away_id"] == meta["team_id"])]

period_sel = period_ui.period_selector("team", _team_games)
is_full_season = period_sel["period"] == "full"

if is_full_season or _team_games.empty:
    hitting_pool, pitching_pool = _season_hitting_pool, _season_pitching_pool
    hitters_roster = st.session_state.team_hitters_roster
    pitchers_roster = st.session_state.team_pitchers_roster
else:
    _team_games_period = stats.filter_by_period(
        _team_games, period_sel["period"], period_sel["last_n_games"],
        period_sel["start_date"], period_sel["end_date"],
    )
    if _team_games_period.empty:
        st.info("No games in the selected period.")
        st.stop()
    _p_start = pd.to_datetime(_team_games_period["game_date"]).min().date()
    _p_end = pd.to_datetime(_team_games_period["game_date"]).max().date()
    try:
        hitting_pool = data_layer.get_team_hitting_leaderboard(
            int(season), meta["sport_id"], start_date=_p_start, end_date=_p_end)
        pitching_pool = data_layer.get_team_pitching_leaderboard(
            int(season), meta["sport_id"], start_date=_p_start, end_date=_p_end)
        hitters_roster = data_layer.get_standard_leaderboard(
            int(season), meta["sport_id"], start_date=_p_start, end_date=_p_end)
        pitchers_roster = data_layer.get_pitching_standard_leaderboard(
            int(season), meta["sport_id"], start_date=_p_start, end_date=_p_end)
    except Exception as e:
        st.warning(f"Couldn't load period-scoped team stats, showing full season instead: {e}")
        hitting_pool, pitching_pool = _season_hitting_pool, _season_pitching_pool
        hitters_roster = st.session_state.team_hitters_roster
        pitchers_roster = st.session_state.team_pitchers_roster

team_hit_row = {}
if hitting_pool is not None and not hitting_pool.empty:
    match = hitting_pool[hitting_pool["team"] == meta["name"]]
    if len(match):
        team_hit_row = match.iloc[0].to_dict()

team_pitch_row = {}
if pitching_pool is not None and not pitching_pool.empty:
    match = pitching_pool[pitching_pool["team"] == meta["name"]]
    if len(match):
        team_pitch_row = match.iloc[0].to_dict()

# ── Hitting section ───────────────────────────────────────────────────────────
theme.section_title("Team Hitting", ACCENT)

h1, h2, h3, h4, h5, h6 = st.columns(6)
h1.metric("Runs/Game", f"{team_hit_row.get('runs_per_game', np.nan):.2f}" if team_hit_row.get("runs_per_game") is not None and pd.notna(team_hit_row.get("runs_per_game")) else "—")
h2.metric("AVG", fmt_rate(team_hit_row.get("avg")))
h3.metric("OBP", fmt_rate(team_hit_row.get("obp")))
h4.metric("SLG", fmt_rate(team_hit_row.get("slg")))
h5.metric("OPS", fmt_rate(team_hit_row.get("ops"), allow_negative=True))
h6.metric("HR", int(team_hit_row["home_runs"]) if team_hit_row.get("home_runs") is not None else "—")

h7, h8, h9 = st.columns(3)
h7.metric("K%", f"{team_hit_row.get('k_pct', np.nan)*100:.1f}%" if team_hit_row.get("k_pct") is not None and pd.notna(team_hit_row.get("k_pct")) else "—")
h8.metric("BB%", f"{team_hit_row.get('bb_pct', np.nan)*100:.1f}%" if team_hit_row.get("bb_pct") is not None and pd.notna(team_hit_row.get("bb_pct")) else "—")
h9.metric("Games", team_hit_row.get("games_played", "—"))

hit_pct_table = stats_team.build_team_percentile_table(
    team_hit_row, hitting_pool, stats_team.TEAM_HITTING_PERCENTILE_METRICS
)
theme.section_title("Percentile Rankings", ACCENT)
st.plotly_chart(charts.percentile_bars(hit_pct_table), width="stretch")

if is_mlb:
    hit_rollup = data_layer.get_team_statcast_rollup(
        meta["name"], st.session_state.team_savant_batting_pool, st.session_state.team_hitters_roster
    )
    if hit_rollup:
        st.markdown(f"**Statcast rollup** (avg across {hit_rollup.get('n_players', 0)} qualified hitters on this team)")
        r1, r2, r3, r4, r5 = st.columns(5)
        r1.metric("Hard-Hit%", f"{hit_rollup.get('hard_hit_pct', np.nan)*100:.1f}%" if pd.notna(hit_rollup.get("hard_hit_pct", np.nan)) else "—")
        r2.metric("Avg Exit Velo", f"{hit_rollup.get('avg_ev', np.nan):.1f} mph" if pd.notna(hit_rollup.get("avg_ev", np.nan)) else "—")
        r3.metric("Chase%", f"{hit_rollup.get('chase_pct', np.nan)*100:.1f}%" if pd.notna(hit_rollup.get("chase_pct", np.nan)) else "—")
        r4.metric("Whiff%", f"{hit_rollup.get('whiff_pct', np.nan)*100:.1f}%" if pd.notna(hit_rollup.get("whiff_pct", np.nan)) else "—")
        r5.metric("Sweet-Spot%", f"{hit_rollup.get('sweet_spot_pct', np.nan)*100:.1f}%" if pd.notna(hit_rollup.get("sweet_spot_pct", np.nan)) else "—")

with st.container(border=True):
    st.markdown("**Hitters on this roster**")
    min_ab = st.number_input("Minimum at-bats to include", min_value=0, max_value=200, value=30, step=5, key="t_min_ab")
    roster = hitters_roster
    if roster is not None and not roster.empty:
        team_roster = roster[(roster["team"] == meta["name"]) & (roster["at_bats"] >= min_ab)].copy()
        if not team_roster.empty:
            team_roster = stats_team.rank_and_format(team_roster, "ops", ascending=False)
            show = team_roster[["Rank", "name", "at_bats", "plate_appearances", "avg", "obp", "slg", "ops",
                                 "home_runs", "k_pct", "bb_pct"]].copy()
            for c in ["avg", "obp", "slg"]:
                show[c] = show[c].map(lambda v: fmt_rate(v, allow_negative=True))
            for c in ["k_pct", "bb_pct"]:
                show[c] = show[c].map(lambda v: f"{v*100:.1f}%" if pd.notna(v) else "—")
            show.columns = ["Rank", "Name", "AB", "PA", "AVG", "OBP", "SLG", "OPS", "HR", "K%", "BB%"]
            st.dataframe(
                show, width="stretch", hide_index=True, height=420,
                column_config={
                    "OPS": st.column_config.ProgressColumn(
                        "OPS", min_value=0.4, max_value=1.1, format="%.3f"
                    ),
                },
            )
        else:
            st.info(f"No hitters on this team with {min_ab}+ at-bats yet.")
    else:
        st.info("Hitter roster leaderboard not loaded.")

st.divider()

# ── Pitching section ──────────────────────────────────────────────────────────
theme.section_title("Team Pitching", ACCENT)

p1, p2, p3, p4, p5, p6 = st.columns(6)
p1.metric("ERA", f"{team_pitch_row.get('era', np.nan):.2f}" if team_pitch_row.get("era") is not None and pd.notna(team_pitch_row.get("era")) else "—")
p2.metric("WHIP", f"{team_pitch_row.get('whip', np.nan):.2f}" if team_pitch_row.get("whip") is not None and pd.notna(team_pitch_row.get("whip")) else "—")
p3.metric("W-L", f"{team_pitch_row.get('wins', '—')}-{team_pitch_row.get('losses', '—')}")
p4.metric("Saves", team_pitch_row.get("saves", "—"))
p5.metric("Runs Allowed/Game", f"{team_pitch_row.get('runs_allowed_per_game', np.nan):.2f}" if team_pitch_row.get("runs_allowed_per_game") is not None and pd.notna(team_pitch_row.get("runs_allowed_per_game")) else "—")
p6.metric("Innings Pitched", f"{team_pitch_row.get('innings_pitched', np.nan):.0f}" if team_pitch_row.get("innings_pitched") is not None and pd.notna(team_pitch_row.get("innings_pitched")) else "—")

p7, p8 = st.columns(2)
p7.metric("K%", f"{team_pitch_row.get('k_pct', np.nan)*100:.1f}%" if team_pitch_row.get("k_pct") is not None and pd.notna(team_pitch_row.get("k_pct")) else "—")
p8.metric("BB%", f"{team_pitch_row.get('bb_pct', np.nan)*100:.1f}%" if team_pitch_row.get("bb_pct") is not None and pd.notna(team_pitch_row.get("bb_pct")) else "—")

pitch_pct_table = stats_team.build_team_percentile_table(
    team_pitch_row, pitching_pool, stats_team.TEAM_PITCHING_PERCENTILE_METRICS
)
theme.section_title("Percentile Rankings", ACCENT)
st.plotly_chart(charts.percentile_bars(pitch_pct_table), width="stretch")

if is_mlb:
    pitch_rollup = data_layer.get_team_statcast_rollup(
        meta["name"], st.session_state.team_savant_pitching_pool, st.session_state.team_pitchers_roster
    )
    if pitch_rollup:
        st.markdown(f"**Statcast rollup** (avg across {pitch_rollup.get('n_players', 0)} qualified pitchers on this team)")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Whiff% (induced)", f"{pitch_rollup.get('whiff_pct', np.nan)*100:.1f}%" if pd.notna(pitch_rollup.get("whiff_pct", np.nan)) else "—")
        r2.metric("Chase% (induced)", f"{pitch_rollup.get('chase_pct', np.nan)*100:.1f}%" if pd.notna(pitch_rollup.get("chase_pct", np.nan)) else "—")
        r3.metric("Hard-Hit% allowed", f"{pitch_rollup.get('hard_hit_pct_against', np.nan)*100:.1f}%" if pd.notna(pitch_rollup.get("hard_hit_pct_against", np.nan)) else "—")
        r4.metric("Avg Exit Velo allowed", f"{pitch_rollup.get('avg_ev_against', np.nan):.1f} mph" if pd.notna(pitch_rollup.get("avg_ev_against", np.nan)) else "—")

with st.container(border=True):
    st.markdown("**Pitchers on this roster** (every pitcher who's appeared — no innings minimum)")
    roster = pitchers_roster
    if roster is not None and not roster.empty:
        team_roster = roster[roster["team"] == meta["name"]].copy()
        if not team_roster.empty:
            team_roster = stats_team.rank_and_format(team_roster, "era", ascending=True)
            show = team_roster[["Rank", "name", "innings_pitched", "era", "whip", "k_pct", "bb_pct",
                                 "wins", "losses", "saves"]].copy()
            show["innings_pitched"] = show["innings_pitched"].map(lambda v: f"{v:.1f}" if pd.notna(v) else "—")
            for c in ["era", "whip"]:
                show[c] = show[c].map(lambda v: f"{v:.2f}" if pd.notna(v) else "—")
            show["bb_pct"] = show["bb_pct"].map(lambda v: f"{v*100:.1f}%" if pd.notna(v) else "—")
            show.columns = ["Rank", "Name", "IP", "ERA", "WHIP", "K%", "BB%", "W", "L", "SV"]
            st.dataframe(
                show, width="stretch", hide_index=True, height=420,
                column_config={
                    "K%": st.column_config.ProgressColumn(
                        "K%", min_value=0.0, max_value=0.4, format="%.3f"
                    ),
                },
            )
        else:
            st.info("No individual pitcher rows matched this team name in the player leaderboard.")
    else:
        st.info("Pitcher roster leaderboard not loaded.")

st.divider()

# ── Pitch-level deep dive (opt-in, heavier pull) ─────────────────────────────
theme.section_title("Pitch-Level Deep Dive", ACCENT)

dd_col1, dd_col2 = st.columns([1, 3])
with dd_col1:
    dd_force_refresh = st.checkbox("Force refresh pitch-level data", value=False, key="t_dd_refresh")
    dd_load_clicked = st.button("Load pitch-level splits", key="t_dd_load", width="stretch")

if dd_load_clicked:
    status = st.empty()
    bar = st.empty()

    def dd_progress(msg):
        status.info(msg)
        bar.empty()

    def dd_game_progress(completed, total):
        status.info(f"Pulling pitch-by-pitch data — {completed} of {total} games…")
        bar.progress(completed / total if total else 0)

    pitch_log = data_layer.get_team_pitch_log(
        team_id=meta["team_id"], team_name=meta["name"], season=int(season), sport_id=meta["sport_id"],
        force_refresh=dd_force_refresh, progress_callback=dd_progress, game_progress_callback=dd_game_progress,
    )
    status.empty()
    bar.empty()
    st.session_state.team_pitch_log = pitch_log

pitch_log = st.session_state.team_pitch_log
if pitch_log is None:
    st.info("Click **Load pitch-level splits** above to see pitch-type performance, discipline, "
            "contact quality, and trend charts for this team.")
elif pitch_log.empty:
    st.warning("No pitch-level data came back for this team/season — the schedule lookup may have "
               "failed (see the debug expander below) or this team hasn't played any games yet.")
else:
    # Reuses the SAME period selection from the top of the page (no
    # separate widget here) — this is exactly what fixes the original
    # complaint: changing the date range at the top now consistently
    # affects the bulk tiles above AND the deep-dive charts below, instead
    # of the deep dive having its own independent control.
    pitch_log_period = stats.filter_by_period(pitch_log, period_sel["period"], period_sel["last_n_games"],
                                               period_sel["start_date"], period_sel["end_date"])
    if pitch_log_period.empty:
        st.info("No games in the selected period.")
        st.stop()

    team_batting_df = pitch_log_period[pitch_log_period["batter_team_id"] == meta["team_id"]]
    team_pitching_df = pitch_log_period[pitch_log_period["pitcher_team_id"] == meta["team_id"]]

    dd_tab_pitchtype, dd_tab_discipline, dd_tab_contact, dd_tab_trend = st.tabs(
        ["Hitting/Pitching by Pitch Type", "Plate Discipline", "Contact Quality", "Trends"]
    )

    with dd_tab_pitchtype:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Team hitting — results vs. pitch type seen**")
            hit_pitch_table = stats.compute_pitch_type_table(team_batting_df)
            st.plotly_chart(charts.pitch_mix_chart(hit_pitch_table), width="stretch")
            if not hit_pitch_table.empty:
                show = hit_pitch_table[["pitch_type", "n_pitches", "usage_pct", "ba", "obp", "slg", "ops", "whiff_pct"]].copy()
                show["usage_pct"] = show["usage_pct"].map(lambda v: f"{v:.0f}%")
                show["whiff_pct"] = show["whiff_pct"].map(lambda v: f"{v:.0f}%")
                for c in ["ba", "obp", "slg", "ops"]:
                    show[c] = show[c].map(lambda v: fmt_rate(v, allow_negative=True))
                show.columns = ["Pitch", "N", "Usage%", "BA", "OBP", "SLG", "OPS", "Whiff%"]
                st.dataframe(show, width="stretch", hide_index=True)
        with c2:
            st.markdown("**Team pitching — results allowed by pitch type thrown**")
            pitch_pitch_table = stats.compute_pitch_type_table(team_pitching_df)
            st.plotly_chart(charts.pitch_mix_chart(pitch_pitch_table), width="stretch")
            if not pitch_pitch_table.empty:
                show = pitch_pitch_table[["pitch_type", "n_pitches", "usage_pct", "ba", "obp", "slg", "ops", "whiff_pct"]].copy()
                show["usage_pct"] = show["usage_pct"].map(lambda v: f"{v:.0f}%")
                show["whiff_pct"] = show["whiff_pct"].map(lambda v: f"{v:.0f}%")
                for c in ["ba", "obp", "slg", "ops"]:
                    show[c] = show[c].map(lambda v: fmt_rate(v, allow_negative=True))
                show.columns = ["Pitch", "N", "Usage%", "BA-against", "OBP-against", "SLG-against", "OPS-against", "Whiff%-induced"]
                st.dataframe(show, width="stretch", hide_index=True)

    with dd_tab_discipline:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Team hitting — swing rate by zone (pitches seen)**")
            st.plotly_chart(charts.discipline_heatmap(team_batting_df), width="stretch")
            hit_disc = stats.compute_plate_discipline(team_batting_df)
            d1, d2, d3 = st.columns(3)
            d1.metric("Chase%", f"{hit_disc['chase_pct']*100:.1f}%" if pd.notna(hit_disc["chase_pct"]) else "—")
            d2.metric("Whiff%", f"{hit_disc['whiff_pct']*100:.1f}%" if pd.notna(hit_disc["whiff_pct"]) else "—")
            d3.metric("Contact%", f"{hit_disc['contact_pct']*100:.1f}%" if pd.notna(hit_disc["contact_pct"]) else "—")
        with c2:
            st.markdown("**Team pitching — swing rate by zone (pitches thrown)**")
            st.plotly_chart(charts.discipline_heatmap(team_pitching_df), width="stretch")
            pitch_disc = stats.compute_plate_discipline(team_pitching_df)
            d4, d5, d6 = st.columns(3)
            d4.metric("Chase% (induced)", f"{pitch_disc['chase_pct']*100:.1f}%" if pd.notna(pitch_disc["chase_pct"]) else "—")
            d5.metric("Whiff% (induced)", f"{pitch_disc['whiff_pct']*100:.1f}%" if pd.notna(pitch_disc["whiff_pct"]) else "—")
            d6.metric("CSW%", f"{pitch_disc['csw_pct']*100:.1f}%" if pd.notna(pitch_disc["csw_pct"]) else "—")

    with dd_tab_contact:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Contact produced (team hitting)**")
            st.plotly_chart(charts.ev_la_scatter(team_batting_df), width="stretch")
            hit_statcast = stats.compute_statcast_summary(team_batting_df)
            hit_enriched = stats.enrich_spray_coordinates(team_batting_df)
            hit_bb = stats.compute_batted_ball_profile(hit_enriched)
            b1, b2, b3 = st.columns(3)
            b1.metric("Hard-Hit%", f"{hit_statcast['hard_hit_pct']*100:.1f}%" if pd.notna(hit_statcast["hard_hit_pct"]) else "—")
            b2.metric("GB%", f"{hit_bb['gb_pct']*100:.0f}%" if pd.notna(hit_bb["gb_pct"]) else "—")
            b3.metric("FB%", f"{hit_bb['fb_pct']*100:.0f}%" if pd.notna(hit_bb["fb_pct"]) else "—")
        with c2:
            st.markdown("**Contact allowed (team pitching)**")
            st.plotly_chart(charts.ev_la_scatter(team_pitching_df), width="stretch")
            pitch_statcast = stats.compute_statcast_summary(team_pitching_df)
            pitch_enriched = stats.enrich_spray_coordinates(team_pitching_df)
            pitch_bb = stats.compute_batted_ball_profile(pitch_enriched)
            b4, b5, b6 = st.columns(3)
            b4.metric("Hard-Hit% allowed", f"{pitch_statcast['hard_hit_pct']*100:.1f}%" if pd.notna(pitch_statcast["hard_hit_pct"]) else "—")
            b5.metric("GB% induced", f"{pitch_bb['gb_pct']*100:.0f}%" if pd.notna(pitch_bb["gb_pct"]) else "—")
            b6.metric("FB% induced", f"{pitch_bb['fb_pct']*100:.0f}%" if pd.notna(pitch_bb["fb_pct"]) else "—")

    with dd_tab_trend:
        run_trend = stats.compute_team_run_trend(pitch_log_period, meta["team_id"], data_layer.get_schedule_lookup(int(season), meta["sport_id"]))
        st.plotly_chart(charts.team_run_trend_chart(run_trend, window=10), width="stretch")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Team hitting trend**")
            hit_trend = stats.compute_rolling_trend(team_batting_df, window=100)
            st.plotly_chart(charts.rolling_trend_chart(hit_trend, 100), width="stretch")
        with c2:
            st.markdown("**Team pitching trend (against)**")
            pitch_trend = stats.compute_rolling_trend(team_pitching_df, window=100)
            st.plotly_chart(charts.rolling_trend_chart(pitch_trend, 100), width="stretch")

st.divider()

with st.expander("Data source status (debug info)"):
    st.write(f"**Team hitting leaderboard:** {'not loaded' if hitting_pool is None or hitting_pool.empty else f'{len(hitting_pool)} teams'}")
    if hitting_pool is not None and not hitting_pool.empty:
        st.caption(f"Columns: {list(hitting_pool.columns)}")
    st.write(f"**Team pitching leaderboard:** {'not loaded' if pitching_pool is None or pitching_pool.empty else f'{len(pitching_pool)} teams'}")
    if pitching_pool is not None and not pitching_pool.empty:
        st.caption(f"Columns: {list(pitching_pool.columns)}")
    st.markdown("Team hitting percentile table:")
    st.dataframe(hit_pct_table, width="stretch", hide_index=True)
    st.markdown("Team pitching percentile table:")
    st.dataframe(pitch_pct_table, width="stretch", hide_index=True)

    pl = st.session_state.team_pitch_log
    if pl is None:
        st.write("**Pitch-level deep dive:** not loaded")
    elif pl.empty:
        st.write("**Pitch-level deep dive:** loaded but empty (0 rows — see warning above)")
    else:
        st.write(f"**Pitch-level deep dive:** {len(pl)} pitch rows across "
                 f"{pl['game_id'].nunique()} games")
        st.caption(f"Has score columns for run trend? {'home_score' in pl.columns and 'away_score' in pl.columns}")

    hitters_all = st.session_state.team_hitters_roster
    pitchers_all = st.session_state.team_pitchers_roster
    st.write(f"**Full league hitting leaderboard (pre-filter):** "
             f"{'not loaded' if hitters_all is None or hitters_all.empty else f'{len(hitters_all)} total players across all teams'}")
    if hitters_all is not None and not hitters_all.empty:
        n_this_team = (hitters_all["team"] == meta["name"]).sum()
        st.caption(f"{n_this_team} of those rows match team name '{meta['name']}'. "
                   f"Sample of team names present: {sorted(hitters_all['team'].dropna().unique())[:8]}")
    hit_fetch_debug = data_layer.get_fetch_debug(f"hitting_{meta['sport_id']}_{season}")
    if hit_fetch_debug:
        st.caption(f"Last raw fetch: {hit_fetch_debug.get('total_rows')} rows across "
                   f"{hit_fetch_debug.get('pages_fetched')} page(s). Request URL (pasteable in a browser): "
                   f"{hit_fetch_debug.get('first_request_url')}")

    st.write(f"**Full league pitching leaderboard (pre-filter):** "
             f"{'not loaded' if pitchers_all is None or pitchers_all.empty else f'{len(pitchers_all)} total players across all teams'}")
    if pitchers_all is not None and not pitchers_all.empty:
        n_this_team = (pitchers_all["team"] == meta["name"]).sum()
        st.caption(f"{n_this_team} of those rows match team name '{meta['name']}'.")
    pitch_fetch_debug = data_layer.get_fetch_debug(f"pitching_{meta['sport_id']}_{season}")
    if pitch_fetch_debug:
        st.caption(f"Last raw fetch: {pitch_fetch_debug.get('total_rows')} rows across "
                   f"{pitch_fetch_debug.get('pages_fetched')} page(s). Request URL (pasteable in a browser): "
                   f"{pitch_fetch_debug.get('first_request_url')}")
