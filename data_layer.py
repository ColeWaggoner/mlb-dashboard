"""
data_layer.py
─────────────
All network access and caching for the dashboard lives here. Three kinds of data:

1. Player universe  - who exists, at which level, this season (roster endpoint).
2. Player pitch log  - every pitch a specific batter has seen this season, pulled
   game-by-game from the live GUMBO feed (this is what powers the spray chart,
   zone chart, pitch mix, etc). Expensive, so cached to disk per player/season/level.
3. League baselines  - season-long rate stats for every qualified hitter at a level,
   used to compute percentile ranks. Pulled in bulk (one or two requests) rather
   than by looping every player's pitch log, which would be far too slow.

NOTE: this was written without the ability to hit statsapi.mlb.com or
baseballsavant.mlb.com from the build sandbox (network egress there is locked
to package registries only). The endpoint shapes below follow the same
conventions already used successfully in your api_scraper.py plus Baseball
Savant's well-documented public CSV leaderboard. If MLB or Savant have changed
a field name since, the debug helpers in app.py (raw JSON expanders) will make
it fast to spot and patch. See README.md "If something breaks" section.
"""

import io
import json
import time
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import requests

from api_scraper import MLB_Scrape

CACHE_DIR = Path(__file__).parent / "cache"
ROSTER_CACHE = CACHE_DIR / "rosters"
PITCH_CACHE = CACHE_DIR / "pitch_data"
LEADERBOARD_CACHE = CACHE_DIR / "leaderboards"
for d in (ROSTER_CACHE, PITCH_CACHE, LEADERBOARD_CACHE):
    d.mkdir(parents=True, exist_ok=True)

# Bump this whenever the processing logic for a cached leaderboard changes
# (renamed column, fixed a scale bug, etc). It's baked into the cache
# filename, so a code update automatically invalidates old cached files
# instead of silently serving stale/wrong data until the 6h TTL expires.
# This is exactly what caused the Hard-Hit%/Chase%/Whiff%/Sweet-Spot% bug to
# persist across a fix: the old parquet file was still "fresh" by the clock.
# v6: switched period-scoped leaderboard fetches from stats=season (which a
# user report showed wasn't actually respecting startDate/endDate at all)
# to stats=byDateRange. The period-scoped cache filename pattern didn't
# change, so without this bump a stale, wrongly-identical-to-season-long
# pool fetched under the old query could keep being served under what
# looks like the same file name.
# v7: get_schedule_lookup now filters out games that haven't been played
# yet (previously returned the full scheduled calendar for the whole
# season) — a stale cached schedule from before this fix would still
# include those future games under the same file name.
# v8: dropped AA/High-A/A from LEVELS (no usable stats at those levels per
# a user report against the live deployment) — a stale cached roster from
# before this change would still list players at those levels.
# v9: Savant leaderboard fetches switched from the broken /leaderboard/
# custom endpoint (returned HTML, not CSV) to the verified-working
# /leaderboard/statcast endpoint, with a different column mapping — a
# stale cached Savant pool from before this fix would be either empty or
# built from a previous, broken attempt.
CACHE_VERSION = 9

# Separate version counter for the per-player/pitcher/team pitch-level caches
# (these never expire on a TTL — they're cached indefinitely, since a
# player's past games don't change — so a bug fix in how the raw game feed
# gets pulled or parsed needs its own explicit invalidation here, or every
# previously-loaded player keeps silently serving the old, wrong rows
# forever). v2: fixed a bug in api_scraper.get_data_df where plate
# appearances whose final recorded event wasn't itself a pitch were being
# dropped entirely. v3: removed non-standard bracket syntax
# (gameType=[R] -> gameType=R) from the game-list/roster request URLs in
# api_scraper.py. v4: de-duplicate game_ids before pulling and drop any
# duplicate (game_id, ab_number, index_play) rows from the result. v5:
# skip non-atBat "action" plays (caught stealing, pickoffs, stolen bases,
# etc.) in get_data_df's outer play loop — these were getting swept up by
# the v2 fix and miscounted as real plate appearances, which is what was
# actually behind counts still running high after v4.
PITCH_LOG_CACHE_VERSION = 5

# Levels the dashboard supports, per the user's chosen scope (MLB + full-season
# affiliated minors). Rookie ball (16) is intentionally excluded.
LEVELS = {
    1:  "MLB",
    11: "AAA",
}

scraper = MLB_Scrape()


# ─────────────────────────────────────────────────────────────────────────────
# Player universe
# ─────────────────────────────────────────────────────────────────────────────

def load_player_universe(season: int, force_refresh: bool = False) -> pd.DataFrame:
    """
    Returns one row per player per level they had a roster spot at, for the
    given season, across every level in LEVELS. Cached to disk for 1 day
    since rosters don't change minute to minute.
    """
    cache_file = ROSTER_CACHE / f"{season}_v{CACHE_VERSION}.parquet"
    if cache_file.exists() and not force_refresh:
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < 24:
            return pd.read_parquet(cache_file)

    frames = []
    for sport_id, level_name in LEVELS.items():
        try:
            df = scraper.get_players(sport_id=sport_id, season=season, game_type=["R"])
            if df is None or len(df) == 0:
                continue
            pdf = df.to_pandas() if hasattr(df, "to_pandas") else df.copy()
            pdf["sport_id"] = sport_id
            pdf["level"] = level_name
            frames.append(pdf)
        except Exception as e:
            print(f"[load_player_universe] failed for sport_id={sport_id}: {e}")

    if not frames:
        return pd.DataFrame(
            columns=["player_id", "name", "position", "team", "sport_id", "level"]
        )

    all_players = pd.concat(frames, ignore_index=True, sort=False)
    all_players = all_players.drop_duplicates(subset=["player_id", "sport_id"])
    all_players["display_name"] = (
        all_players["name"].astype(str) + "  —  " + all_players["level"].astype(str)
    )
    all_players.to_parquet(cache_file, index=False)
    return all_players


# ─────────────────────────────────────────────────────────────────────────────
# Per-player pitch log
# ─────────────────────────────────────────────────────────────────────────────

def _pitch_cache_path(player_id: int, season: int, sport_id: int) -> Path:
    return PITCH_CACHE / f"{sport_id}_{season}_{player_id}_v{PITCH_LOG_CACHE_VERSION}.parquet"


def _dedupe_game_ids(game_ids: list, progress_callback=None) -> list:
    """De-duplicates a game_ids list before pulling, preserving order. This
    exists because MLB's per-player gameLog hydration can list the same
    gamePk more than once (e.g. a suspended-and-resumed game showing up as
    two log entries for the same underlying game) — pulling and processing
    that game twice would duplicate every plate appearance in it, inflating
    PA/AB counts. Diagnosed from a user report of counts running slightly
    *high* versus Baseball Reference (extra PAs, not missing ones — the
    opposite signature from the dropped-plate-appearance bug fixed earlier).
    """
    unique_ids = list(dict.fromkeys(game_ids))
    n_dupes = len(game_ids) - len(unique_ids)
    if n_dupes > 0 and progress_callback:
        progress_callback(f"Note: {n_dupes} duplicate game ID(s) found in the schedule and skipped.")
    return unique_ids


def _dedupe_pitch_rows(pdf: pd.DataFrame) -> pd.DataFrame:
    """Defense-in-depth companion to _dedupe_game_ids: drops any rows that
    are exact duplicates on (game_id, ab_number, index_play) — that triple
    should uniquely identify a single pitch/play event within one player's
    log, so a repeat is unambiguously a data artifact (from duplicate game
    pulls or any other source), never a legitimate second row. Applied to
    the dataframe right before caching, so both fresh pulls and anything
    already cached under an older, undeduplicated version get cleaned up
    on next refresh.
    """
    if pdf is None or pdf.empty or not {"game_id", "ab_number", "index_play"}.issubset(pdf.columns):
        return pdf
    return pdf.drop_duplicates(subset=["game_id", "ab_number", "index_play"], keep="first")


def get_batter_pitch_log(
    player_id: int,
    player_name: str,
    season: int,
    sport_id: int,
    force_refresh: bool = False,
    progress_callback=None,
    game_progress_callback=None,
) -> pd.DataFrame:
    """
    Pulls every pitch/plate-appearance event for one batter this season, using
    the same GUMBO-feed approach as the original notebook, but scoped to the
    player's own game list instead of a full team schedule (much less data to
    pull per look-up). Cached to disk indefinitely per (player, season, level);
    use force_refresh=True to re-pull (e.g. after new games have been played).

    progress_callback(msg: str): occasional text status updates (unchanged).
    game_progress_callback(completed: int, total: int): called after each
    individual game finishes downloading, for a real, incrementally-updating
    progress bar — see MLB_Scrape.get_data's own docstring for why this
    exists (the tqdm progress bar in that method renders to the terminal via
    stdout, which a web UI never sees).
    """
    cache_file = _pitch_cache_path(player_id, season, sport_id)
    if cache_file.exists() and not force_refresh:
        return pd.read_parquet(cache_file)

    if progress_callback:
        progress_callback(f"Finding {player_name}'s games this season…")

    game_ids = scraper.get_player_games_list(
        player_id=player_id, season=season, sport_id=sport_id, game_type=["R"], pitching=False
    )
    game_ids = _dedupe_game_ids(game_ids, progress_callback)
    if not game_ids:
        empty = pd.DataFrame()
        empty.to_parquet(cache_file, index=False)
        return empty

    if progress_callback:
        progress_callback(f"Pulling pitch-by-pitch data for {len(game_ids)} games…")

    game_data = scraper.get_data(game_list_input=game_ids, game_progress_callback=game_progress_callback)

    if progress_callback:
        progress_callback("Converting to a table…")

    data_df = scraper.get_data_df(data_list=game_data)
    pdf = data_df.to_pandas() if hasattr(data_df, "to_pandas") else data_df.copy()
    pdf = _dedupe_pitch_rows(pdf)

    player_df = pdf[pdf["batter_id"] == player_id].copy()
    if player_df.empty and player_name:
        # Fallback in case batter_id typing mismatches (str vs int) slipped through
        player_df = pdf[pdf["batter_name"] == player_name].copy()

    player_df.sort_values("game_date", inplace=True, ignore_index=True)
    player_df.to_parquet(cache_file, index=False)
    return player_df


# ─────────────────────────────────────────────────────────────────────────────
# League baselines for percentile ranks — hitting
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_stats_splits(season: int, sport_id: int, group: str,
                         start_date=None, end_date=None) -> tuple:
    """Shared MLB Stats API season-leaderboard fetch for either group=hitting
    or group=pitching. Returns (splits_list, debug_info).

    Two things going on here:
    1. `playerPool=all` — without it, this endpoint appears to default to
       something narrower than "everyone with a stat line" (consistent with
       team roster tables showing only ~5 hitters and ~4 pitchers — roughly
       the "regulars" you'd expect from an official-qualification-style
       default, not an actual roster). Explicitly asking for the full pool
       is the fix if that's what's happening.
    2. Pagination via `offset`, kept from before as a second safeguard in
       case there's *also* a per-request cap once the full pool is
       requested.
    debug_info (pages fetched, first request URL, total rows) gets
    surfaced in the Team Dashboard's debug expander so this is inspectable
    without editing code — if the count is still wrong, the URL there is
    directly pasteable into a browser to see the raw response.

    start_date/end_date (optional): scopes every player's totals to just
    that date range instead of the whole season — used for the "compare
    against the same period" percentile mode. Uses `stats=byDateRange`
    instead of `stats=season` when a date range is given — the first
    attempt kept `stats=season` and just appended startDate/endDate, and a
    user reported the resulting percentiles never changed regardless of
    the toggle, consistent with those params being silently ignored.
    `stats=season` is a fixed "full season totals" aggregation mode;
    `byDateRange` is the stat type actually meant for this. This is a
    second, more targeted attempt at the same live endpoint, still not
    independently verified from this build environment — the debug
    expander shows both the exact request URL and a pool-mean comparison
    so this is checkable at a glance rather than another silent guess.
    """
    all_splits = []
    offset = 0
    page_size = 500
    pages_fetched = 0
    first_url = None
    is_period_scoped = start_date is not None and end_date is not None
    stats_type = "byDateRange" if is_period_scoped else "season"
    date_params = f"&startDate={start_date}&endDate={end_date}" if is_period_scoped else ""
    for _ in range(20):  # hard safety cap: 20 x 500 = 10,000 rows, way more than any season needs
        url = (
            "https://statsapi.mlb.com/api/v1/stats"
            f"?stats={stats_type}&group={group}&season={season}&sportId={sport_id}"
            f"&gameType=R&playerPool=all&limit={page_size}&offset={offset}{date_params}"
        )
        if first_url is None:
            first_url = url
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        page_splits = []
        for stat_block in payload.get("stats", []):
            page_splits.extend(stat_block.get("splits", []))
        all_splits.extend(page_splits)
        pages_fetched += 1
        if len(page_splits) < page_size:
            break
        offset += page_size
    debug_info = {"pages_fetched": pages_fetched, "total_rows": len(all_splits), "first_request_url": first_url}
    return all_splits, debug_info


def _save_fetch_debug(key: str, debug_info: dict) -> None:
    with open(LEADERBOARD_CACHE / f"fetch_debug_{key}.json", "w") as f:
        json.dump(debug_info, f)


def get_fetch_debug(key: str) -> dict:
    """Reads back the debug_info saved by the last _fetch_stats_splits call
    for this key (persists independently of the parquet TTL, so even a
    cache-served load can show what the last real fetch actually returned)."""
    p = LEADERBOARD_CACHE / f"fetch_debug_{key}.json"
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


def get_standard_leaderboard(season: int, sport_id: int, force_refresh: bool = False,
                              start_date=None, end_date=None) -> pd.DataFrame:
    """
    Bulk season hitting totals for every player at a level, straight from the
    MLB Stats API stats endpoint (one request covers everyone — no need to
    pull individual pitch logs). Used for AVG/OBP/SLG/OPS/BB%/K% percentiles.

    Qualification (min PA) is computed locally as 3.1 x the max games played
    by anyone in the pool, which mirrors how MLB defines "qualified" at
    season's end and scales reasonably mid-season too — and, since
    games_played itself comes back scoped to whatever date range was
    requested, this threshold naturally scales down for a period-scoped
    pool instead of needing separate logic.

    start_date/end_date (optional): scopes every player's totals to just
    that date range — used for the "compare against the same period"
    percentile mode. Cached separately from the season-long pool (distinct
    filename), since it's genuinely different data. See _fetch_stats_splits
    for the caveat on this date-scoping capability being unverified live.
    """
    is_period_scoped = start_date is not None and end_date is not None
    if is_period_scoped:
        cache_file = LEADERBOARD_CACHE / f"{sport_id}_{season}_standard_v{CACHE_VERSION}_{start_date}_{end_date}.parquet"
    else:
        cache_file = LEADERBOARD_CACHE / f"{sport_id}_{season}_standard_v{CACHE_VERSION}.parquet"
    if cache_file.exists() and not force_refresh:
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < 6:
            return pd.read_parquet(cache_file)

    splits, debug_info = _fetch_stats_splits(season, sport_id, "hitting", start_date, end_date)
    _save_fetch_debug(f"hitting_{sport_id}_{season}" + (f"_{start_date}_{end_date}" if is_period_scoped else ""),
                       debug_info)
    rows = []
    for split in splits:
        stat = split.get("stat", {})
        player = split.get("player", {})
        team = split.get("team", {})
        rows.append({
            "player_id": player.get("id"),
            "name": player.get("fullName"),
            "team": team.get("name"),
            "games_played": stat.get("gamesPlayed", 0),
            "plate_appearances": stat.get("plateAppearances", 0),
            "at_bats": stat.get("atBats", 0),
            "hits": stat.get("hits", 0),
            "doubles": stat.get("doubles", 0),
            "triples": stat.get("triples", 0),
            "home_runs": stat.get("homeRuns", 0),
            "walks": stat.get("baseOnBalls", 0),
            "strikeouts": stat.get("strikeOuts", 0),
            "hbp": stat.get("hitByPitch", 0),
            "sac_fly": stat.get("sacFlies", 0),
            "avg": _safe_float(stat.get("avg")),
            "obp": _safe_float(stat.get("obp")),
            "slg": _safe_float(stat.get("slg")),
            "ops": _safe_float(stat.get("ops")),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        df.to_parquet(cache_file, index=False)
        return df

    df["k_pct"] = np.where(df["plate_appearances"] > 0, df["strikeouts"] / df["plate_appearances"], np.nan)
    df["bb_pct"] = np.where(df["plate_appearances"] > 0, df["walks"] / df["plate_appearances"], np.nan)
    df["iso"] = df["slg"] - df["avg"]

    max_gp = df["games_played"].max() if len(df) else 0
    qualified_pa = 3.1 * max_gp
    df["qualified"] = df["plate_appearances"] >= qualified_pa

    df.to_parquet(cache_file, index=False)
    if not is_period_scoped:
        with open(LEADERBOARD_CACHE / f"{sport_id}_{season}_standard_meta.json", "w") as f:
            json.dump({"qualified_pa_threshold": qualified_pa}, f)
    return df


def get_qualified_pa_threshold(season: int, sport_id: int) -> float:
    meta_file = LEADERBOARD_CACHE / f"{sport_id}_{season}_standard_meta.json"
    if meta_file.exists():
        with open(meta_file) as f:
            return json.load(f).get("qualified_pa_threshold", 0)
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# League baselines for percentile ranks — pitching
# ─────────────────────────────────────────────────────────────────────────────

def parse_innings_pitched(ip) -> float:
    """MLB represents partial innings as .1/.2 = 1 or 2 OUTS, not tenths — so
    '182.1' means 182 and 1/3 innings, not 182.1 innings. Converts to a real
    float so IP can be summed/thresholded correctly."""
    if ip is None:
        return 0.0
    s = str(ip)
    whole, _, frac = s.partition(".")
    try:
        whole_val = float(whole) if whole not in ("", "-") else 0.0
    except ValueError:
        return 0.0
    outs = 0
    if frac:
        try:
            outs = int(frac[0])
        except ValueError:
            outs = 0
    return whole_val + outs / 3.0


def get_max_team_games(season: int, sport_id: int, force_refresh: bool = False,
                        start_date=None, end_date=None) -> int:
    """How many games has the leading team played so far this season (or,
    if start_date/end_date given, within that date range) at this level —
    used as the basis for the 1-IP-per-team-game 'qualified' pitching
    threshold (mirrors the batting 3.1-PA-per-team-game rule)."""
    sched = get_schedule_lookup(season, sport_id, force_refresh=force_refresh)
    if sched.empty:
        return 162 if sport_id == 1 else 140
    if start_date is not None and end_date is not None and "game_date" in sched.columns:
        dates = pd.to_datetime(sched["game_date"])
        sched = sched[(dates >= pd.Timestamp(start_date)) & (dates <= pd.Timestamp(end_date))]
        if sched.empty:
            return 0
    counts = pd.concat([sched["home_id"], sched["away_id"]]).value_counts()
    return int(counts.max()) if len(counts) else (162 if sport_id == 1 else 140)


def get_pitching_standard_leaderboard(season: int, sport_id: int, force_refresh: bool = False,
                                       start_date=None, end_date=None) -> pd.DataFrame:
    """Bulk season pitching totals for every pitcher at a level. Used for
    ERA/WHIP/K%/BB%/HR9 percentiles. 'Qualified' = IP >= 1 x team games played
    so far — the same rule as the official ERA title, which restricts the
    qualified pool mostly to starters. See get_pitching_percentile_pool() in
    stats_pitching.py for how relievers get a fairer comparison pool instead.

    start_date/end_date (optional): scopes every pitcher's totals to just
    that date range — same "compare against the same period" mode as
    get_standard_leaderboard, cached separately for the same reason."""
    is_period_scoped = start_date is not None and end_date is not None
    if is_period_scoped:
        cache_file = LEADERBOARD_CACHE / f"{sport_id}_{season}_pitching_standard_v{CACHE_VERSION}_{start_date}_{end_date}.parquet"
    else:
        cache_file = LEADERBOARD_CACHE / f"{sport_id}_{season}_pitching_standard_v{CACHE_VERSION}.parquet"
    if cache_file.exists() and not force_refresh:
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < 6:
            return pd.read_parquet(cache_file)

    splits, debug_info = _fetch_stats_splits(season, sport_id, "pitching", start_date, end_date)
    _save_fetch_debug(f"pitching_{sport_id}_{season}" + (f"_{start_date}_{end_date}" if is_period_scoped else ""),
                       debug_info)
    rows = []
    for split in splits:
        stat = split.get("stat", {})
        player = split.get("player", {})
        team = split.get("team", {})
        ip_real = parse_innings_pitched(stat.get("inningsPitched"))
        bf = stat.get("battersFaced", 0) or 0
        rows.append({
            "player_id": player.get("id"),
            "name": player.get("fullName"),
            "team": team.get("name"),
            "games_played": stat.get("gamesPlayed", 0),
            "games_started": stat.get("gamesStarted", 0),
            "innings_pitched": ip_real,
            "batters_faced": bf,
            "hits_allowed": stat.get("hits", 0),
            "walks": stat.get("baseOnBalls", 0),
            "strikeouts": stat.get("strikeOuts", 0),
            "home_runs": stat.get("homeRuns", 0),
            "earned_runs": stat.get("earnedRuns", 0),
            "wins": stat.get("wins", 0),
            "losses": stat.get("losses", 0),
            "saves": stat.get("saves", 0),
            "holds": stat.get("holds", 0),
            "era": _safe_float(stat.get("era")),
            "whip": _safe_float(stat.get("whip")),
            "k_per_9": _safe_float(stat.get("strikeoutsPer9Inn")),
            "bb_per_9": _safe_float(stat.get("walksPer9Inn")),
            "hr_per_9": _safe_float(stat.get("homeRunsPer9")),
            "k_bb_ratio": _safe_float(stat.get("strikeoutWalkRatio")),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        df.to_parquet(cache_file, index=False)
        return df

    df["k_pct"] = np.where(df["batters_faced"] > 0, df["strikeouts"] / df["batters_faced"], np.nan)
    df["bb_pct"] = np.where(df["batters_faced"] > 0, df["walks"] / df["batters_faced"], np.nan)
    df["k_bb_pct"] = df["k_pct"] - df["bb_pct"]
    # Simple constant-FIP approximation (league-average FIP constant varies
    # year to year, ~3.0-3.2; using a fixed 3.10 here — labeled "approx" in
    # the UI since the exact seasonal constant isn't available via this API).
    df["fip"] = np.where(
        df["innings_pitched"] > 0,
        ((13 * df["home_runs"]) + (3 * df["walks"]) - (2 * df["strikeouts"])) / df["innings_pitched"] + 3.10,
        np.nan,
    )

    max_team_games = get_max_team_games(season, sport_id, start_date=start_date, end_date=end_date)
    qualified_ip = 1.0 * max_team_games
    df["qualified"] = df["innings_pitched"] >= qualified_ip
    # A much lower bar so relievers (who will essentially never hit the
    # official qualified threshold) still land in a meaningful comparison
    # pool — scales down early in the season so it isn't absurdly high in
    # April, capped at 20 IP once the season is underway.
    relief_ip_floor = min(20.0, qualified_ip * 0.15)
    df["relief_pool"] = df["innings_pitched"] >= relief_ip_floor

    df.to_parquet(cache_file, index=False)
    if not is_period_scoped:
        with open(LEADERBOARD_CACHE / f"{sport_id}_{season}_pitching_standard_meta.json", "w") as f:
            json.dump({"qualified_ip_threshold": qualified_ip, "relief_ip_floor": relief_ip_floor}, f)
    return df


def get_qualified_ip_thresholds(season: int, sport_id: int) -> dict:
    meta_file = LEADERBOARD_CACHE / f"{sport_id}_{season}_pitching_standard_meta.json"
    if meta_file.exists():
        with open(meta_file) as f:
            return json.load(f)
    return {"qualified_ip_threshold": 0, "relief_ip_floor": 0}


def get_pitcher_official_season_stats(player_id: int, season: int, sport_id: int,
                                        force_refresh: bool = False,
                                        start_date=None, end_date=None) -> dict:
    """Official pitching line for ONE pitcher (ERA, WHIP, W-L, saves, IP,
    etc) straight from MLB's per-player stats endpoint. Deliberately NOT
    derived from the pitch-by-pitch feed — earned-run/unearned-run judgment
    calls aren't reliably recoverable from play-by-play, so the box-score
    numbers come from the same official source as any stats site.

    start_date/end_date (optional): scopes the line to just that date
    range via stats=byDateRange instead of stats=season — same mechanism
    and same live-verification caveat as get_standard_leaderboard's
    period-scoped mode. Used so the Pitcher Dashboard's headline tiles can
    actually respond to the period selector with a genuinely official
    (not derived/approximated) date-scoped line, rather than staying
    frozen at full-season."""
    is_period_scoped = start_date is not None and end_date is not None
    if is_period_scoped:
        cache_file = LEADERBOARD_CACHE / f"pitcher_{player_id}_{season}_{sport_id}_official_v{CACHE_VERSION}_{start_date}_{end_date}.json"
    else:
        cache_file = LEADERBOARD_CACHE / f"pitcher_{player_id}_{season}_{sport_id}_official_v{CACHE_VERSION}.json"
    if cache_file.exists() and not force_refresh:
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < 3:
            with open(cache_file) as f:
                return json.load(f)

    stats_type = "byDateRange" if is_period_scoped else "season"
    date_params = f"&startDate={start_date}&endDate={end_date}" if is_period_scoped else ""
    url = (
        f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats"
        f"?stats={stats_type}&group=pitching&season={season}&sportId={sport_id}&gameType=R{date_params}"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    payload = resp.json()

    splits = []
    for block in payload.get("stats", []):
        splits.extend(block.get("splits", []))
    if not splits:
        result = {}
    else:
        stat = splits[0].get("stat", {})
        ip_real = parse_innings_pitched(stat.get("inningsPitched"))
        bf = stat.get("battersFaced", 0) or 0
        k = stat.get("strikeOuts", 0) or 0
        bb = stat.get("baseOnBalls", 0) or 0
        hr = stat.get("homeRuns", 0) or 0
        result = {
            "games_played": stat.get("gamesPlayed", 0),
            "games_started": stat.get("gamesStarted", 0),
            "innings_pitched_display": stat.get("inningsPitched"),
            "innings_pitched": ip_real,
            "wins": stat.get("wins", 0),
            "losses": stat.get("losses", 0),
            "saves": stat.get("saves", 0),
            "holds": stat.get("holds", 0),
            "blown_saves": stat.get("blownSaves", 0),
            "era": _safe_float(stat.get("era")),
            "whip": _safe_float(stat.get("whip")),
            "hits_allowed": stat.get("hits", 0),
            "earned_runs": stat.get("earnedRuns", 0),
            "walks": bb,
            "strikeouts": k,
            "home_runs": hr,
            "hit_batsmen": stat.get("hitBatsmen", 0),
            "batters_faced": bf,
            "k_per_9": _safe_float(stat.get("strikeoutsPer9Inn")),
            "bb_per_9": _safe_float(stat.get("walksPer9Inn")),
            "hr_per_9": _safe_float(stat.get("homeRunsPer9")),
            "k_pct": _safe_div(k, bf),
            "bb_pct": _safe_div(bb, bf),
            "fip": ((13 * hr) + (3 * bb) - (2 * k)) / ip_real + 3.10 if ip_real > 0 else np.nan,
        }

    with open(cache_file, "w") as f:
        json.dump(result, f)
    return result


PITCHING_SAVANT_METRICS = {
    "player_id": "player_id",
    "player_name": "name",
    # Two name variants mapped to each target: the classic leaderboard's
    # long-established naming (avg_hit_speed, ev95percent,
    # anglesweetspotpercent) and the newer/custom-tool naming this app
    # originally guessed (exit_velocity_avg, hard_hit_percent,
    # sweet_spot_percent). Only one is likely to actually be present in
    # any given response; mapping both to the same target means whichever
    # one Savant is actually using gets picked up without needing to know
    # in advance which era of column names this endpoint uses.
    "avg_hit_speed": "avg_ev_against",
    "exit_velocity_avg": "avg_ev_against",
    "ev95percent": "hard_hit_pct_against",
    "hard_hit_percent": "hard_hit_pct_against",
    "anglesweetspotpercent": "sweet_spot_pct_against",
    "sweet_spot_percent": "sweet_spot_pct_against",
}

PITCHING_PERCENT_SCALE_COLUMNS = {"hard_hit_pct_against", "sweet_spot_pct_against"}


def get_pitching_savant_percentile_pool(season: int, force_refresh: bool = False) -> pd.DataFrame:
    """Baseball Savant's classic Statcast batted-ball-against leaderboard
    for qualified MLB pitchers (Hard-Hit%/Avg Exit Velo/Sweet-Spot% against
    only — see the note on get_savant_percentile_pool for why Chase%/Whiff%
    aren't sourced from here)."""
    cache_file = LEADERBOARD_CACHE / f"{season}_savant_pitching_v{CACHE_VERSION}.parquet"
    if cache_file.exists() and not force_refresh:
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < 6:
            return pd.read_parquet(cache_file)

    url = (
        "https://baseballsavant.mlb.com/leaderboard/statcast"
        f"?type=pitcher&year={season}&position=&team=&min=q&csv=true"
    )
    raw = _fetch_savant_csv(url)
    df = _process_savant_csv(raw, PITCHING_SAVANT_METRICS, PITCHING_PERCENT_SCALE_COLUMNS)
    df.to_parquet(cache_file, index=False)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Baseball Savant — shared batter leaderboard machinery
# ─────────────────────────────────────────────────────────────────────────────

SAVANT_METRICS = {
    "player_id": "player_id",
    "player_name": "name",
    # See the comment on PITCHING_SAVANT_METRICS above for why two name
    # variants map to each target.
    "avg_hit_speed": "avg_ev",
    "exit_velocity_avg": "avg_ev",
    "ev95percent": "hard_hit_pct",
    "hard_hit_percent": "hard_hit_pct",
    "anglesweetspotpercent": "sweet_spot_pct",
    "sweet_spot_percent": "sweet_spot_pct",
}

# Columns that Savant expresses as 0-100 (literal percentages) rather than the
# 0-1 fractions this app computes everywhere else. Auto-detected anyway (see
# _normalize_percent_scale) but listed here as the set that gets checked.
PERCENT_SCALE_COLUMNS = {"hard_hit_pct", "sweet_spot_pct"}


def _normalize_percent_scale(series: pd.Series) -> pd.Series:
    """Rescales a 0-100 percent column to a 0-1 fraction. Auto-detects via the
    median rather than assuming, so this stays correct even if Savant changes
    a column's convention later: fractions are essentially never above ~1.5,
    literal percentages essentially always are."""
    s = pd.to_numeric(series, errors="coerce")
    if s.dropna().empty:
        return s
    return s / 100.0 if s.dropna().median() > 1.5 else s


def _process_savant_csv(raw: pd.DataFrame, metrics_map: dict = None, percent_cols: set = None) -> pd.DataFrame:
    """Renames Savant's raw CSV columns to our internal names and normalizes
    scale. Split out from get_savant_percentile_pool so it can be unit tested
    without a network call. Defaults to the batter mapping for backwards
    compatibility; pass PITCHING_SAVANT_METRICS/PITCHING_PERCENT_SCALE_COLUMNS
    for the pitcher leaderboard.

    metrics_map can map more than one source column name to the same
    target (a hedge against not knowing in advance which naming
    convention Savant's response is actually using — see SAVANT_METRICS).
    That means metrics_map.values() itself can contain duplicates, and if
    more than one of those source variants happens to be present in a
    given response, raw.rename() produces genuine duplicate-named
    columns. Both are de-duplicated here (keeping the first) so a lookup
    like df["avg_ev"] always returns a Series, never a same-named-column
    DataFrame that breaks _normalize_percent_scale."""
    metrics_map = metrics_map or SAVANT_METRICS
    percent_cols = percent_cols if percent_cols is not None else PERCENT_SCALE_COLUMNS

    rename_map = {c: metrics_map[c] for c in raw.columns if c in metrics_map}
    if not rename_map:
        raise RuntimeError(
            "Baseball Savant's response didn't contain any of the expected columns "
            f"(looked for {sorted(metrics_map)}). Actual columns received: "
            f"{list(raw.columns)}. Savant likely renamed a field or changed the "
            "response format — check the metrics mapping in data_layer.py against that list."
        )
    df = raw.rename(columns=rename_map)
    keep_cols = list(dict.fromkeys(v for v in metrics_map.values() if v in df.columns))
    df = df[keep_cols]
    df = df.loc[:, ~df.columns.duplicated()]
    for col in percent_cols:
        if col in df.columns:
            df[col] = _normalize_percent_scale(df[col])
    return df


def _fetch_savant_csv(url: str) -> pd.DataFrame:
    """Shared network call + sanity checks for any Baseball Savant custom
    leaderboard export (batter or pitcher).

    A user report against the live deployment: percentile rankings that
    depend on this (Statcast metrics — Hard-Hit%, Chase%, Whiff%, etc.)
    stopped showing up, and this endpoint started returning the plain
    HTML leaderboard page instead of CSV data. The request already had a
    realistic User-Agent/Accept/Referer before any of this, so simple
    header spoofing wasn't the original fix either. Current header set is
    fuller (Accept-Language, Accept-Encoding, sec-fetch-*, sec-ch-ua) in
    case Savant's bot detection checks for a more complete fingerprint
    than just User-Agent — pure additive realism, no behavioral downside.
    An earlier attempt also added a "warm-up" request to the plain
    leaderboard page first (to pick up cookies before the real request);
    that's been reverted since a report that this exact error started
    after a recent change points at it directly — firing two requests
    back to back within milliseconds is exactly the kind of timing
    pattern real bot detection looks for, so it plausibly made things
    worse rather than better.

    Being direct about what's still unverified: even with this reverted,
    there's a real possibility Baseball Savant blocks by the requesting
    SERVER'S IP RANGE rather than anything in the request itself —
    Streamlit Community Cloud's IPs are a known, documented range, and
    blocking cloud-hosting-provider traffic specifically (regardless of
    headers) is a common defense against exactly this kind of scraping.
    If that's what's happening, no header/request change fixes it from
    here. The "first 300 chars" of the actual response in the error
    message below is the next real data point if this still fails.
    """
    browser_headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        # NEVER add "br" (Brotli) here. A live-deployment report showed the
        # response coming back as garbled binary once the URL fix below
        # started actually getting a CSV response from Savant — advertising
        # "br" support (this app's own prior addition) makes some servers
        # respond with a Brotli-compressed body, and requests can only
        # auto-decompress that if the optional brotli/brotlicffi package is
        # installed, which it isn't in this environment (confirmed
        # directly: `import brotli` fails here). Without it, the raw
        # compressed bytes get returned as if they were the final content
        # and .text mis-decodes them as UTF-8, producing exactly that kind
        # of garbage. "gzip, deflate" is requests' own actual default when
        # this header isn't set at all — same value, just made explicit so
        # it's not accidentally re-widened later.
        "Accept-Encoding": "gzip, deflate",
        "Referer": "https://baseballsavant.mlb.com/leaderboard/statcast",
        "sec-ch-ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Connection": "keep-alive",
    }

    # NOTE: an earlier version of this also made a "warm-up" request to the
    # plain leaderboard page first, to pick up cookies before the real CSV
    # request. Reverted — a user report that this exact error started
    # after a recent change is the most likely explanation, and that
    # warm-up step is the strongest candidate: two requests fired back to
    # back within milliseconds is exactly the kind of timing pattern real
    # bot detection looks for (no human loads a page and clicks "export"
    # that fast), so it plausibly made things worse rather than better.
    # Back to one request, keeping the fuller header set since that part
    # is pure realism with no behavioral downside.
    resp = requests.get(url, timeout=30, headers={**browser_headers, "Accept": "text/csv,*/*;q=0.8"})
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    content_encoding = resp.headers.get("Content-Encoding", "")
    stripped = resp.text.strip()
    first_line = stripped.splitlines()[0] if stripped else ""
    looks_like_html = first_line.lstrip().startswith("<")
    looks_like_csv = "," in first_line
    # A response that's actually still-compressed binary (e.g. a
    # Content-Encoding requests couldn't auto-decompress) decodes as UTF-8
    # into mostly unprintable/control characters rather than real text —
    # named explicitly in the error below rather than left to look like a
    # generic parsing failure, since that's exactly what happened once
    # here already (see the Accept-Encoding comment above).
    if stripped:
        unprintable_ratio = sum(1 for c in stripped[:300] if not c.isprintable() and c not in "\n\r\t") / min(len(stripped), 300)
        looks_like_garbled_binary = unprintable_ratio > 0.15
    else:
        looks_like_garbled_binary = False

    if not stripped or looks_like_html or not looks_like_csv or looks_like_garbled_binary:
        encoding_hint = (
            f" Content-Encoding was {content_encoding!r} — if this looks like garbled binary "
            "rather than HTML, that's likely a compressed response requests couldn't "
            "auto-decompress (e.g. Brotli without the optional brotli package installed); "
            "check the Accept-Encoding header this request sent rather than assuming it's HTML "
            "or a blocked request." if looks_like_garbled_binary else ""
        )
        raise RuntimeError(
            f"Baseball Savant returned something that doesn't look like CSV "
            f"(Content-Type: {content_type or 'unknown'}).{encoding_hint} First 300 chars: "
            f"{resp.text[:300]!r}. It may be blocking automated requests or the "
            "leaderboard URL format has changed."
        )

    raw = pd.read_csv(io.StringIO(resp.text))
    if raw.empty or len(raw.columns) <= 1:
        raise RuntimeError(
            f"Baseball Savant's CSV parsed to an unexpectedly small table "
            f"({raw.shape}). First 300 chars of the raw response: {resp.text[:300]!r}"
        )
    return raw


def get_savant_percentile_pool(season: int, force_refresh: bool = False) -> pd.DataFrame:
    """
    Baseball Savant's classic Statcast batted-ball leaderboard for qualified
    MLB batters (Hard-Hit%, Avg Exit Velo, Sweet-Spot%). This does NOT exist
    for minor-league levels; Statcast percentile ranks are MLB-only in this
    dashboard for that reason.

    A live-deployment bug report showed this was returning the plain HTML
    leaderboard page instead of CSV data, breaking every Statcast percentile
    row. Root cause: this was using `/leaderboard/custom` — the interactive,
    JavaScript-driven leaderboard BUILDER tool — with a `csv=true` parameter
    that tool's server apparently doesn't act on (its CSV export may be
    entirely client-side JS working from already-loaded page data, rather
    than a server-side response to that URL parameter). No amount of header
    tuning could have fixed that, since the URL itself wasn't the right one.

    Switched to `/leaderboard/statcast` — a different, older, simpler
    endpoint verified against pybaseball's actual source code (a real,
    widely-used, actively-maintained library that depends on this exact URL
    working: `leaderboard/statcast?type=batter&year={year}&position=&team=
    &min={min}&csv=true`). This endpoint is specifically the classic
    batted-ball-quality leaderboard, so it covers Hard-Hit%/Avg Exit Velo/
    Sweet-Spot% but NOT Chase%/Whiff% (those live on Savant's separate
    "Swing & Take" leaderboard) — independently confirmed elsewhere as
    currently broken on Baseball Savant's own end (a different, actively-
    maintained package's own "Known Issues" notes document that exact CSV
    export returning headers with no data rows). Chase%/Whiff% percentile
    ranks are consequently not available from Savant right now regardless
    of what this app does; they just won't show a percentile (the same
    graceful "value known, no percentile source" handling already used for
    minor-league players, where Statcast percentiles were never available
    at all — see build_percentile_table).

    The exact column names this endpoint returns still aren't independently
    verified from this build environment — SAVANT_METRICS maps two plausible
    naming conventions (the classic leaderboard's long-established names,
    and the newer names this app was previously guessing) to the same
    targets, so whichever one is actually in use gets picked up. If NEITHER
    matches, _process_savant_csv raises a clear error showing the actual
    column names received, so a next attempt has real data instead of
    another guess.
    """
    cache_file = LEADERBOARD_CACHE / f"{season}_savant_v{CACHE_VERSION}.parquet"
    if cache_file.exists() and not force_refresh:
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < 6:
            return pd.read_parquet(cache_file)

    url = (
        "https://baseballsavant.mlb.com/leaderboard/statcast"
        f"?type=batter&year={season}&position=&team=&min=q&csv=true"
    )
    raw = _fetch_savant_csv(url)
    df = _process_savant_csv(raw, SAVANT_METRICS, PERCENT_SCALE_COLUMNS)
    df.to_parquet(cache_file, index=False)
    return df


def get_schedule_lookup(season: int, sport_id: int, force_refresh: bool = False) -> pd.DataFrame:
    """game_id -> home_id/away_id, so we can tag each pitch event as a home or
    road game. Cached per season/level.

    Only includes games that have ALREADY BEEN PLAYED (game_date strictly
    before today). The raw schedule endpoint returns the full scheduled
    calendar for the whole season — for a team 100 games into a 162-game
    season, that's still 162 rows, 62 of them games that haven't happened
    yet. Anything that treats "rows in the schedule" as "games played" was
    silently wrong as a result: reported directly as the Team Dashboard's
    "Last N Games" ending up pulling from games 153-162 of a season the
    team is only ~100 games into, which obviously aren't real games yet.
    This also affects get_max_team_games (the pitcher qualified-IP
    threshold) and the Team Dashboard's pitch-level deep dive (which would
    otherwise try to fetch play-by-play for games that haven't been played)
    — fixing it here, once, rather than patching each of those separately.

    Uses game_date rather than the schedule's own game-state field, since
    that field's exact coded values aren't verified from this build
    environment and a date comparison ("is this before today") doesn't
    depend on guessing them correctly.
    """
    cache_file = LEADERBOARD_CACHE / f"{sport_id}_{season}_schedule_v{CACHE_VERSION}.parquet"
    if cache_file.exists() and not force_refresh:
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < 6:
            return pd.read_parquet(cache_file)

    try:
        sched = scraper.get_schedule(year_input=[season], sport_id=[sport_id], game_type=["R"])
        sdf = sched.to_pandas() if hasattr(sched, "to_pandas") else sched.copy()
        sdf = sdf[["game_id", "date", "home_id", "away_id"]].drop_duplicates().rename(columns={"date": "game_date"})

        game_dates = pd.to_datetime(sdf["game_date"])
        sdf = sdf[game_dates < pd.Timestamp(date.today())]

        sdf.to_parquet(cache_file, index=False)
        return sdf
    except Exception as e:
        print(f"[get_schedule_lookup] failed: {e}")
        return pd.DataFrame(columns=["game_id", "game_date", "home_id", "away_id"])


def attach_home_away(df: pd.DataFrame, season: int, sport_id: int,
                      team_id_col: str = "batter_team_id") -> pd.DataFrame:
    """Best-effort join to add an is_home boolean column, based on whichever
    side's team_id you pass (batter_team_id for a batter's own log,
    pitcher_team_id for a pitcher's own log). Leaves the column out (rather
    than raising) if the schedule lookup fails, so Home/Away splits just
    won't render instead of breaking the app."""
    if df is None or df.empty or "game_id" not in df.columns or team_id_col not in df.columns:
        return df
    sched = get_schedule_lookup(season, sport_id)
    if sched.empty:
        return df
    # Only take home_id/away_id from the schedule — df already has its own
    # game_date, and merging the schedule's copy in too would collide into
    # game_date_x/game_date_y suffixes and silently break every downstream
    # df["game_date"] reference.
    merged = df.merge(sched[["game_id", "home_id", "away_id"]], on="game_id", how="left")
    # object dtype (not bool) on purpose: unmatched games need a real NaN for
    # "unknown", and recent pandas raises on assigning NaN into a bool column.
    is_home = (merged[team_id_col] == merged["home_id"]).astype(object)
    is_home[merged["home_id"].isna()] = np.nan
    merged["is_home"] = is_home
    return merged


def _safe_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def _safe_div(n, d):
    try:
        return float(n) / float(d) if d else np.nan
    except (TypeError, ValueError, ZeroDivisionError):
        return np.nan


def percentile_rank(value: float, pool: pd.Series) -> float:
    """% of the qualified pool that `value` beats or ties. Returns None if the
    pool is empty or value is missing."""
    pool = pool.dropna()
    if value is None or (isinstance(value, float) and np.isnan(value)) or len(pool) == 0:
        return None
    return float((pool <= value).mean() * 100)


# ─────────────────────────────────────────────────────────────────────────────
# Team-level stats (bulk endpoints — no per-player pitch pulls needed)
# ─────────────────────────────────────────────────────────────────────────────

def get_team_list(season: int, sport_id: int, force_refresh: bool = False) -> pd.DataFrame:
    """Active teams at a level/season, straight from the teams endpoint with
    explicit sportId/season filters (api_scraper's own get_teams() doesn't
    take these, so this queries the same API directly instead)."""
    cache_file = ROSTER_CACHE / f"teams_{sport_id}_{season}_v{CACHE_VERSION}.parquet"
    if cache_file.exists() and not force_refresh:
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < 24:
            return pd.read_parquet(cache_file)

    url = f"https://statsapi.mlb.com/api/v1/teams?sportId={sport_id}&season={season}&activeStatus=Yes"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    payload = resp.json()

    rows = []
    for t in payload.get("teams", []):
        rows.append({
            "team_id": t.get("id"),
            "name": t.get("name"),
            "abbreviation": t.get("abbreviation"),
            "league_name": (t.get("league") or {}).get("name"),
        })
    df = pd.DataFrame(rows).drop_duplicates(subset=["team_id"]).sort_values("name")
    df.to_parquet(cache_file, index=False)
    return df


def _fetch_team_stats_splits(season: int, sport_id: int, group: str, start_date=None, end_date=None) -> list:
    """Bulk season stat line for every TEAM at a level (one request), from
    the plural teams/stats endpoint — the team-level equivalent of
    _fetch_stats_splits. NOTE: unverified against the live API from this
    build environment; if this comes back empty, the debug expander on the
    Team Dashboard will show the raw response shape to help diagnose it.

    start_date/end_date (optional): scopes every team's totals to just
    that date range, via stats=byDateRange instead of stats=season — same
    mechanism as the player-level leaderboards."""
    is_period_scoped = start_date is not None and end_date is not None
    stats_type = "byDateRange" if is_period_scoped else "season"
    date_params = f"&startDate={start_date}&endDate={end_date}" if is_period_scoped else ""
    url = (
        "https://statsapi.mlb.com/api/v1/teams/stats"
        f"?stats={stats_type}&group={group}&season={season}&sportId={sport_id}&gameType=R{date_params}"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    splits = []
    for stat_block in payload.get("stats", []):
        splits.extend(stat_block.get("splits", []))
    return splits


def get_team_hitting_leaderboard(season: int, sport_id: int, force_refresh: bool = False,
                                  start_date=None, end_date=None) -> pd.DataFrame:
    """Every team's aggregate hitting line at a level, in one request. Used
    for both this team's own tiles and the percentile pool of every other
    team to compare against — both naturally stay consistent with each
    other since they come from the same one call.

    start_date/end_date (optional): scopes every team's totals to just
    that date range — used by the Team Dashboard's period selector.
    Cached separately from the season-long pool."""
    is_period_scoped = start_date is not None and end_date is not None
    if is_period_scoped:
        cache_file = LEADERBOARD_CACHE / f"{sport_id}_{season}_team_hitting_v{CACHE_VERSION}_{start_date}_{end_date}.parquet"
    else:
        cache_file = LEADERBOARD_CACHE / f"{sport_id}_{season}_team_hitting_v{CACHE_VERSION}.parquet"
    if cache_file.exists() and not force_refresh:
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < 6:
            return pd.read_parquet(cache_file)

    splits = _fetch_team_stats_splits(season, sport_id, "hitting", start_date, end_date)
    rows = []
    for split in splits:
        stat = split.get("stat", {})
        team = split.get("team", {})
        pa = stat.get("plateAppearances", 0) or 0
        rows.append({
            "team_id": team.get("id"),
            "team": team.get("name"),
            "games_played": stat.get("gamesPlayed", 0),
            "plate_appearances": pa,
            "at_bats": stat.get("atBats", 0),
            "runs": stat.get("runs", 0),
            "hits": stat.get("hits", 0),
            "home_runs": stat.get("homeRuns", 0),
            "walks": stat.get("baseOnBalls", 0),
            "strikeouts": stat.get("strikeOuts", 0),
            "avg": _safe_float(stat.get("avg")),
            "obp": _safe_float(stat.get("obp")),
            "slg": _safe_float(stat.get("slg")),
            "ops": _safe_float(stat.get("ops")),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["k_pct"] = np.where(df["plate_appearances"] > 0, df["strikeouts"] / df["plate_appearances"], np.nan)
        df["bb_pct"] = np.where(df["plate_appearances"] > 0, df["walks"] / df["plate_appearances"], np.nan)
        df["runs_per_game"] = np.where(df["games_played"] > 0, df["runs"] / df["games_played"], np.nan)
    df.to_parquet(cache_file, index=False)
    return df


def get_team_pitching_leaderboard(season: int, sport_id: int, force_refresh: bool = False,
                                   start_date=None, end_date=None) -> pd.DataFrame:
    """Every team's aggregate pitching line at a level, in one request.
    start_date/end_date (optional): same period-scoping as
    get_team_hitting_leaderboard."""
    is_period_scoped = start_date is not None and end_date is not None
    if is_period_scoped:
        cache_file = LEADERBOARD_CACHE / f"{sport_id}_{season}_team_pitching_v{CACHE_VERSION}_{start_date}_{end_date}.parquet"
    else:
        cache_file = LEADERBOARD_CACHE / f"{sport_id}_{season}_team_pitching_v{CACHE_VERSION}.parquet"
    if cache_file.exists() and not force_refresh:
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < 6:
            return pd.read_parquet(cache_file)

    splits = _fetch_team_stats_splits(season, sport_id, "pitching", start_date, end_date)
    rows = []
    for split in splits:
        stat = split.get("stat", {})
        team = split.get("team", {})
        bf = stat.get("battersFaced", 0) or 0
        ip_real = parse_innings_pitched(stat.get("inningsPitched"))
        rows.append({
            "team_id": team.get("id"),
            "team": team.get("name"),
            "games_played": stat.get("gamesPlayed", 0),
            "innings_pitched": ip_real,
            "batters_faced": bf,
            "runs_allowed": stat.get("runs", 0),
            "earned_runs": stat.get("earnedRuns", 0),
            "hits_allowed": stat.get("hits", 0),
            "walks": stat.get("baseOnBalls", 0),
            "strikeouts": stat.get("strikeOuts", 0),
            "home_runs": stat.get("homeRuns", 0),
            "saves": stat.get("saves", 0),
            "wins": stat.get("wins", 0),
            "losses": stat.get("losses", 0),
            "era": _safe_float(stat.get("era")),
            "whip": _safe_float(stat.get("whip")),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["k_pct"] = np.where(df["batters_faced"] > 0, df["strikeouts"] / df["batters_faced"], np.nan)
        df["bb_pct"] = np.where(df["batters_faced"] > 0, df["walks"] / df["batters_faced"], np.nan)
        df["runs_allowed_per_game"] = np.where(df["games_played"] > 0, df["runs_allowed"] / df["games_played"], np.nan)
    df.to_parquet(cache_file, index=False)
    return df


def get_team_statcast_rollup(team_name: str, savant_pool: pd.DataFrame, standard_pool: pd.DataFrame) -> dict:
    """Best-effort team-level Statcast averages: joins the (player-level,
    already-fetched) Savant pool to the standard leaderboard on player_id to
    recover each player's team, then averages across that team's players who
    show up in the qualified Savant pool. This is a rollup of qualified
    players only, not the full active roster — labeled as such in the UI."""
    if savant_pool is None or savant_pool.empty or standard_pool is None or standard_pool.empty:
        return {}
    if "player_id" not in savant_pool.columns or "player_id" not in standard_pool.columns:
        return {}

    merged = savant_pool.merge(standard_pool[["player_id", "team"]], on="player_id", how="left")
    team_rows = merged[merged["team"] == team_name]
    if team_rows.empty:
        return {}

    result = {"n_players": len(team_rows)}
    for col in team_rows.columns:
        if col in ("player_id", "name", "team"):
            continue
        if pd.api.types.is_numeric_dtype(team_rows[col]):
            result[col] = team_rows[col].mean()
    return result


def _team_pitch_cache_path(team_id: int, season: int, sport_id: int) -> Path:
    return PITCH_CACHE / f"team_{sport_id}_{season}_{team_id}_v{PITCH_LOG_CACHE_VERSION}.parquet"


def get_team_pitch_log(
    team_id: int,
    team_name: str,
    season: int,
    sport_id: int,
    force_refresh: bool = False,
    progress_callback=None,
    game_progress_callback=None,
) -> pd.DataFrame:
    """Full-season pitch-by-pitch log for every game a team played, both
    sides of the ball at once (a game's feed always has that team batting AND
    pitching, since they only play against someone else once). This is the
    same scale of pull the original notebook did for one team's schedule —
    genuinely heavier than any other fetch in this app (up to ~160+ games
    instead of one player's subset of them), so it's kept as a separate,
    opt-in step on the Team Dashboard rather than something that loads
    automatically. Cached to disk afterward like everything else.

    Filter the result on batter_team_id == team_id for the team's hitting
    log, or pitcher_team_id == team_id for its pitching log.

    progress_callback(msg: str): occasional text status updates (unchanged).
    game_progress_callback(completed: int, total: int): called after each
    individual game finishes downloading — see get_batter_pitch_log's
    docstring for why this exists as a second, separate callback.
    """
    cache_file = _team_pitch_cache_path(team_id, season, sport_id)
    if cache_file.exists() and not force_refresh:
        return pd.read_parquet(cache_file)

    if progress_callback:
        progress_callback(f"Finding {team_name}'s games this season…")

    sched = get_schedule_lookup(season, sport_id, force_refresh=force_refresh)
    if sched.empty:
        empty = pd.DataFrame()
        empty.to_parquet(cache_file, index=False)
        return empty

    team_games = sched[(sched["home_id"] == team_id) | (sched["away_id"] == team_id)]
    game_ids = team_games["game_id"].dropna().unique().tolist()  # already de-duped via .unique()
    game_ids = _dedupe_game_ids(game_ids, progress_callback)
    if not game_ids:
        empty = pd.DataFrame()
        empty.to_parquet(cache_file, index=False)
        return empty

    if progress_callback:
        progress_callback(
            f"Pulling pitch-by-pitch data for {len(game_ids)} games — this is a full season "
            "for one team, so it can take a few minutes…"
        )

    game_data = scraper.get_data(game_list_input=game_ids, game_progress_callback=game_progress_callback)

    if progress_callback:
        progress_callback("Converting to a table…")

    data_df = scraper.get_data_df(data_list=game_data)
    pdf = data_df.to_pandas() if hasattr(data_df, "to_pandas") else data_df.copy()
    pdf = _dedupe_pitch_rows(pdf)
    pdf.sort_values("game_date", inplace=True, ignore_index=True)
    pdf.to_parquet(cache_file, index=False)
    return pdf


# ─────────────────────────────────────────────────────────────────────────────
# Per-pitcher pitch log
# ─────────────────────────────────────────────────────────────────────────────

def _pitcher_cache_path(player_id: int, season: int, sport_id: int) -> Path:
    return PITCH_CACHE / f"pitching_{sport_id}_{season}_{player_id}_v{PITCH_LOG_CACHE_VERSION}.parquet"


def get_pitcher_pitch_log(
    player_id: int,
    player_name: str,
    season: int,
    sport_id: int,
    force_refresh: bool = False,
    progress_callback=None,
    game_progress_callback=None,
) -> pd.DataFrame:
    """Every pitch a pitcher has thrown this season, scoped to their own game
    list (mirrors get_batter_pitch_log, filtered on pitcher_id instead).

    progress_callback(msg: str): occasional text status updates (unchanged).
    game_progress_callback(completed: int, total: int): called after each
    individual game finishes downloading — see get_batter_pitch_log's
    docstring for why this exists as a second, separate callback."""
    cache_file = _pitcher_cache_path(player_id, season, sport_id)
    if cache_file.exists() and not force_refresh:
        return pd.read_parquet(cache_file)

    if progress_callback:
        progress_callback(f"Finding {player_name}'s appearances this season…")

    game_ids = scraper.get_player_games_list(
        player_id=player_id, season=season, sport_id=sport_id, game_type=["R"], pitching=True
    )
    game_ids = _dedupe_game_ids(game_ids, progress_callback)
    if not game_ids:
        empty = pd.DataFrame()
        empty.to_parquet(cache_file, index=False)
        return empty

    if progress_callback:
        progress_callback(f"Pulling pitch-by-pitch data for {len(game_ids)} games…")

    game_data = scraper.get_data(game_list_input=game_ids, game_progress_callback=game_progress_callback)

    if progress_callback:
        progress_callback("Converting to a table…")

    data_df = scraper.get_data_df(data_list=game_data)
    pdf = data_df.to_pandas() if hasattr(data_df, "to_pandas") else data_df.copy()
    pdf = _dedupe_pitch_rows(pdf)

    player_df = pdf[pdf["pitcher_id"] == player_id].copy()
    if player_df.empty and player_name:
        player_df = pdf[pdf["pitcher_name"] == player_name].copy()

    player_df.sort_values("game_date", inplace=True, ignore_index=True)
    player_df.to_parquet(cache_file, index=False)
    return player_df
