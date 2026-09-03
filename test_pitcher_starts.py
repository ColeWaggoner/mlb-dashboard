"""
Regression tests for two pitcher-page fixes:

1. "Last N Games" wasn't actually changing anything the user could see —
   the headline ERA/WHIP/etc tiles were deliberately built to always stay
   full-season (to avoid deriving earned-run-sensitive stats from
   play-by-play). Fixed by fetching a genuinely official, date-scoped line
   via stats=byDateRange instead — same mechanism as the batter page's
   period-scoped league pool, applied to the per-player endpoint.
2. The period control now reads "Last N Starts" and counts/selects from
   starts specifically, not just any appearance — relevant for anyone who
   has both starts and relief outings in the same season, where "last N
   games" and "last N starts" are genuinely different sets.
"""
import json

import numpy as np
import pandas as pd
import requests

import data_layer
import stats
import stats_pitching


def test_get_pitcher_start_game_ids():
    df = pd.DataFrame({
        "game_id": [1, 1, 1, 2, 2, 3, 3, 3],
        "inning":  [1, 2, 3, 6, 7, 1, 1, 2],
    })
    starts = stats_pitching.get_pitcher_start_game_ids(df)
    assert starts == {1, 3}, starts
    print("get_pitcher_start_game_ids: correctly identifies starts (inning 1) vs relief (later innings)")


def test_filter_by_period_restrict_to_game_ids():
    df = pd.DataFrame({
        "game_id": [1, 1, 2, 2, 3, 3, 4, 4, 5, 5],
        "game_date": ["2026-04-01"] * 2 + ["2026-04-05"] * 2 + ["2026-04-10"] * 2 + ["2026-04-15"] * 2 + ["2026-04-20"] * 2,
        "event_type": ["single", "strikeout"] * 5,
    })
    # Unrestricted: last 2 games = 4, 5
    r1 = stats.filter_by_period(df, "last_n", last_n_games=2)
    assert set(r1["game_id"]) == {4, 5}

    # Restricted to starts {1, 3, 5}: last 2 STARTS = 3, 5 (skipping non-start games 2, 4)
    r2 = stats.filter_by_period(df, "last_n", last_n_games=2, restrict_to_game_ids={1, 3, 5})
    assert set(r2["game_id"]) == {3, 5}, set(r2["game_id"])
    print("filter_by_period: restrict_to_game_ids correctly limits 'last N' to a starts-only subset")


def test_pitcher_official_stats_date_scoping():
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
        return FakeResp({"stats": [{"splits": [{"stat": {
            "gamesPlayed": 3, "gamesStarted": 3, "inningsPitched": "18.0", "wins": 2, "losses": 0,
            "era": "2.50", "whip": "1.05", "strikeOuts": 20, "baseOnBalls": 5, "homeRuns": 2,
            "battersFaced": 70, "strikeoutsPer9Inn": "10.0", "walksPer9Inn": "2.5", "homeRunsPer9": "1.0",
        }}]}]})

    requests.get = fake_get

    data_layer.get_pitcher_official_season_stats(999, 2026, 1, force_refresh=True)
    assert "startDate" not in seen_urls[-1]
    assert "stats=season" in seen_urls[-1]

    data_layer.get_pitcher_official_season_stats(
        999, 2026, 1, force_refresh=True, start_date="2026-04-16", end_date="2026-04-21"
    )
    assert "stats=byDateRange" in seen_urls[-1]
    assert "startDate=2026-04-16" in seen_urls[-1] and "endDate=2026-04-21" in seen_urls[-1]
    print("get_pitcher_official_season_stats: uses stats=byDateRange with correct dates when period-scoped")


if __name__ == "__main__":
    test_get_pitcher_start_game_ids()
    test_filter_by_period_restrict_to_game_ids()
    test_pitcher_official_stats_date_scoping()
    print("\nALL PITCHER LAST-N-STARTS REGRESSION TESTS PASSED")
