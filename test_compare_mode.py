"""
Regression tests for two things added/fixed while building the "Same-Period
League" percentile comparison toggle:

1. get_schedule_lookup() now also returns game_date (needed to date-scope
   get_max_team_games for period-scoped pitching qualification). Adding that
   column created a real risk of colliding with a caller's own game_date
   column on merge — this happened in two places (attach_home_away and
   compute_team_run_trend) and both are covered here directly, using
   synthetic data so this doesn't depend on any real data export.

2. The compare-mode toggle itself: get_standard_leaderboard's date-scoped
   path builds the correct URL and produces a distinct, separately-cached
   pool from the season-long one.
"""
import pandas as pd

import data_layer
import stats


def test_attach_home_away_no_column_collision():
    fake_schedule = pd.DataFrame({
        "game_id": [1, 2], "game_date": ["2026-04-01", "2026-04-02"],
        "home_id": [136, 133], "away_id": [133, 136],
    })
    data_layer.get_schedule_lookup = lambda season, sport_id, force_refresh=False: fake_schedule

    # Team 136 is home in game 1, away in game 2 — exercises both branches.
    pitch_df = pd.DataFrame({
        "game_id": [1, 2], "game_date": ["2026-04-01", "2026-04-02"],
        "batter_team_id": [136, 136],
    })
    result = data_layer.attach_home_away(pitch_df, 2026, 1)
    assert "game_date" in result.columns
    assert "game_date_x" not in result.columns and "game_date_y" not in result.columns
    assert list(result["game_date"]) == ["2026-04-01", "2026-04-02"], "game_date got corrupted by the merge"
    assert list(result["is_home"]) == [True, False], result["is_home"].tolist()
    print("attach_home_away: no column collision, game_date and is_home both correct")


def test_compute_team_run_trend_no_column_collision():
    fake_schedule = pd.DataFrame({
        "game_id": [1, 2, 3, 4], "game_date": ["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04"],
        "home_id": [136, 133, 136, 133], "away_id": [133, 136, 133, 136],
    })
    run_df = pd.DataFrame({
        "game_id": [1, 1, 2, 2, 3, 3, 4, 4],
        "game_date": ["2026-04-01"] * 2 + ["2026-04-02"] * 2 + ["2026-04-03"] * 2 + ["2026-04-04"] * 2,
        "home_score": [3, 4, 2, 2, 5, 5, 1, 1], "away_score": [1, 2, 5, 5, 3, 3, 0, 0],
    })
    trend = stats.compute_team_run_trend(run_df, team_id=136, schedule_df=fake_schedule, window=3)
    assert not trend.empty
    assert "game_date" in trend.columns
    print("compute_team_run_trend: no column collision, merge succeeded")


def test_max_team_games_date_scoping():
    fake_schedule = pd.DataFrame({
        "game_id": list(range(1, 11)),
        "game_date": ["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04", "2026-04-05",
                      "2026-04-10", "2026-04-11", "2026-04-12", "2026-04-13", "2026-04-14"],
        "home_id": [136] * 10, "away_id": [133] * 10,
    })
    data_layer.get_schedule_lookup = lambda season, sport_id, force_refresh=False: fake_schedule

    full = data_layer.get_max_team_games(2026, 1)
    assert full == 10
    scoped = data_layer.get_max_team_games(2026, 1, start_date="2026-04-01", end_date="2026-04-05")
    assert scoped == 5
    print("get_max_team_games: full=10, date-scoped(Apr1-5)=5 — both correct")


def test_standard_leaderboard_period_scoping():
    import json
    import requests

    class FakeResp:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self):
            pass

    seen_urls = []

    def fake_get(url, **kwargs):
        seen_urls.append(url)
        return FakeResp({"stats": [{"splits": [
            {"player": {"id": 1, "fullName": "Batter A"}, "team": {"name": "Seattle Mariners"},
             "stat": {"gamesPlayed": 5, "plateAppearances": 22, "atBats": 17, "hits": 4,
                       "avg": ".235", "obp": ".409", "slg": ".471"}},
        ]}]})

    requests.get = fake_get

    pool_full = data_layer.get_standard_leaderboard(2026, 11, force_refresh=True)
    assert "startDate" not in seen_urls[-1]

    pool_period = data_layer.get_standard_leaderboard(
        2026, 11, force_refresh=True, start_date="2026-04-10", end_date="2026-04-20"
    )
    assert "startDate=2026-04-10" in seen_urls[-1] and "endDate=2026-04-20" in seen_urls[-1]

    full_cache = data_layer.LEADERBOARD_CACHE
    files = sorted(p.name for p in full_cache.glob("11_2026_standard*"))
    assert any("2026-04-10" in f for f in files), "period-scoped cache file not created with a distinct name"
    assert f"11_2026_standard_v{data_layer.CACHE_VERSION}.parquet" in files, "season-long cache file missing"
    print("get_standard_leaderboard: period-scoped fetch uses correct URL + separate cache file")


if __name__ == "__main__":
    test_attach_home_away_no_column_collision()
    test_compute_team_run_trend_no_column_collision()
    test_max_team_games_date_scoping()
    test_standard_leaderboard_period_scoping()
    print("\nALL COMPARE-MODE / SCHEDULE-COLLISION REGRESSION TESTS PASSED")
