"""
Regression test for a user report: changing the date range on the Team
Dashboard didn't update the big tiles (runs per game, hitting/pitching
totals) at all. Root cause: those tiles come from bulk season-total team
endpoints, and there was no top-level period selector wired to them in the
first place — only the separate Pitch-Level Deep Dive section had its own
period control, which only ever affected its own charts, not the main
tiles above it.

Fixed by adding one period selector at the top of the page that:
1. Translates "Last N Games"/a custom range into an actual date range
   using this team's own schedule.
2. Re-fetches genuinely date-scoped hitting/pitching/roster leaderboards
   for that range (stats=byDateRange, same mechanism as the batter/pitcher
   fixes).
3. Is reused by the Deep Dive section too, instead of that section having
   its own separate, second period control.

This test proves the tiles actually change value, not just that the page
renders without exceptions.
"""
import pandas as pd

import data_layer


def test_team_runs_per_game_responds_to_period_selector():
    fake_teams = pd.DataFrame([
        {"team_id": 136, "name": "Seattle Mariners", "abbreviation": "SEA", "league_name": "American League"},
    ])
    fake_team_hitting_full = pd.DataFrame([{
        "team_id": 136, "team": "Seattle Mariners", "games_played": 120, "plate_appearances": 4600,
        "at_bats": 4100, "runs": 560, "hits": 1020, "home_runs": 165, "walks": 400, "strikeouts": 1050,
        "avg": 0.249, "obp": 0.320, "slg": 0.420, "ops": 0.740, "k_pct": 0.228, "bb_pct": 0.087,
        "runs_per_game": 4.67,
    }])
    fake_team_pitching_full = pd.DataFrame([{
        "team_id": 136, "team": "Seattle Mariners", "games_played": 120, "innings_pitched": 1080.0,
        "batters_faced": 4500, "runs_allowed": 480, "earned_runs": 440, "hits_allowed": 950,
        "walks": 380, "strikeouts": 1100, "home_runs": 120, "saves": 30, "wins": 65, "losses": 55,
        "era": 3.67, "whip": 1.23, "k_pct": 0.244, "bb_pct": 0.084, "runs_allowed_per_game": 4.0,
    }])
    fake_hitters_roster = pd.DataFrame([{
        "player_id": 1, "name": "Batter A", "team": "Seattle Mariners", "plate_appearances": 550,
        "at_bats": 500, "avg": 0.280, "obp": 0.360, "slg": 0.480, "ops": 0.840, "home_runs": 28,
        "k_pct": 0.20, "bb_pct": 0.10, "qualified": True,
    }])
    fake_pitchers_roster = pd.DataFrame([{
        "player_id": 10, "name": "Pitcher A", "team": "Seattle Mariners", "innings_pitched": 180.0,
        "era": 3.10, "whip": 1.05, "k_pct": 0.28, "bb_pct": 0.06, "wins": 14, "losses": 6, "saves": 0,
        "qualified": True, "relief_pool": True,
    }])
    fake_schedule = pd.DataFrame({
        "game_id": list(range(1, 21)),
        "game_date": pd.date_range("2026-04-01", periods=20, freq="3D").strftime("%Y-%m-%d"),
        "home_id": [136] * 20, "away_id": [133] * 20,
    })

    calls = []

    def fake_team_hitting(season, sport_id, force_refresh=False, start_date=None, end_date=None):
        calls.append(("hitting", start_date, end_date))
        if start_date is not None:
            return pd.DataFrame([{
                "team_id": 136, "team": "Seattle Mariners", "games_played": 10, "plate_appearances": 380,
                "at_bats": 340, "runs": 68, "hits": 95, "home_runs": 18, "walks": 35, "strikeouts": 80,
                "avg": 0.279, "obp": 0.355, "slg": 0.510, "ops": 0.865, "k_pct": 0.21, "bb_pct": 0.09,
                "runs_per_game": 6.80,
            }])
        return fake_team_hitting_full.copy()

    def fake_team_pitching(season, sport_id, force_refresh=False, start_date=None, end_date=None):
        calls.append(("pitching", start_date, end_date))
        return fake_team_pitching_full.copy()

    data_layer.get_team_list = lambda season, sport_id, force_refresh=False: fake_teams.copy()
    data_layer.get_team_hitting_leaderboard = fake_team_hitting
    data_layer.get_team_pitching_leaderboard = fake_team_pitching
    data_layer.get_standard_leaderboard = (
        lambda season, sport_id, force_refresh=False, start_date=None, end_date=None: fake_hitters_roster.copy()
    )
    data_layer.get_pitching_standard_leaderboard = (
        lambda season, sport_id, force_refresh=False, start_date=None, end_date=None: fake_pitchers_roster.copy()
    )
    data_layer.get_savant_percentile_pool = lambda season, force_refresh=False: pd.DataFrame()
    data_layer.get_pitching_savant_percentile_pool = lambda season, force_refresh=False: pd.DataFrame()
    data_layer.get_schedule_lookup = lambda season, sport_id, force_refresh=False: fake_schedule.copy()

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file("views/team_dashboard.py", default_timeout=60)
    at.run()
    at.selectbox(key="t_team").select("Seattle Mariners")
    at.run()
    [b for b in at.button if b.label == "Load team"][0].click()
    at.run()
    assert not at.exception, f"Load exception: {list(at.exception)}"

    metrics = {m.label: m.value for m in at.get("metric")}
    assert metrics.get("Runs/Game") == "4.67", metrics.get("Runs/Game")
    assert metrics.get("AVG") == ".249", metrics.get("AVG")

    period_selectbox = [sb for sb in at.selectbox if sb.key == "team_period_choice"][0]
    period_selectbox.select("Last N Games")
    at.run()
    assert not at.exception, f"Exception selecting period: {list(at.exception)}"

    n_input = [ni for ni in at.number_input if ni.key == "team_period_n"][0]
    n_input.set_value(10)
    at.run()
    assert not at.exception, f"Exception setting N=10: {list(at.exception)}"

    metrics2 = {m.label: m.value for m in at.get("metric")}
    assert metrics2.get("Runs/Game") == "6.80", metrics2.get("Runs/Game")
    assert metrics2.get("Runs/Game") != metrics.get("Runs/Game")
    assert metrics2.get("AVG") != metrics.get("AVG")

    hitting_calls = [c for c in calls if c[0] == "hitting"]
    assert any(c[1] is not None for c in hitting_calls), "period-scoped fetch was never actually made"

    print("Full season Runs/Game:", metrics.get("Runs/Game"), "-> Last 10 Games Runs/Game:", metrics2.get("Runs/Game"))
    print("TEAM DASHBOARD PERIOD SELECTOR: Runs/Game and AVG tiles genuinely respond to the period selector")


def test_schedule_lookup_excludes_unplayed_games():
    """The actual root cause behind the reported bug: get_schedule_lookup
    returned the full scheduled calendar for the season (e.g. 162 rows for
    an MLB team), not just games that have been played. A team ~100 games
    into its season would then have "Last N Games" computing from games
    153-162 of that 162-game schedule — games that haven't happened yet,
    so the resulting charts had nothing real to show. Fixed by filtering
    get_schedule_lookup itself to game_date < today, which also fixes the
    pitcher qualified-IP threshold (get_max_team_games) as a side effect,
    since that was pulling from the same unfiltered schedule."""
    import datetime

    today = datetime.date.today()
    past_dates = [str(today - datetime.timedelta(days=200 - i)) for i in range(100)]
    future_dates = [str(today + datetime.timedelta(days=i + 1)) for i in range(62)]

    class FakeScheduleResult:
        def __init__(self, df):
            self._df = df

        def to_pandas(self):
            return self._df

    fake_raw_schedule = pd.DataFrame({
        "game_id": list(range(1, 163)), "date": past_dates + future_dates,
        "home_id": [136] * 162, "away_id": [133] * 162,
    })
    data_layer.scraper.get_schedule = lambda **kwargs: FakeScheduleResult(fake_raw_schedule)

    result = data_layer.get_schedule_lookup(2026, 1, force_refresh=True)
    assert len(result) == 100, f"expected 100 already-played games, got {len(result)}"
    assert pd.to_datetime(result["game_date"]).max().date() < today

    max_games = data_layer.get_max_team_games(2026, 1, force_refresh=True)
    assert max_games == 100, f"get_max_team_games should also reflect only played games, got {max_games}"

    print("get_schedule_lookup / get_max_team_games: both correctly exclude unplayed future games")


if __name__ == "__main__":
    # Order matters: the first test monkey-patches data_layer.get_schedule_lookup
    # directly (replacing the whole function, not just the underlying scraper
    # call it makes), which would otherwise leak into the second test and
    # make it test the mock instead of the real filtering logic.
    test_schedule_lookup_excludes_unplayed_games()
    test_team_runs_per_game_responds_to_period_selector()
    print("\nALL TEAM PERIOD-SCOPING REGRESSION TESTS PASSED")
