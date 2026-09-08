"""
Regression tests for a user question: the per-game progress shown in a
terminal (via tqdm inside MLB_Scrape.get_data) is invisible in the actual
web UI, since tqdm writes directly to stdout — a real, incrementally-
updating st.progress() bar wasn't possible before because nothing in the
data-pulling code called back into the page as each game finished.

Added game_progress_callback(completed, total) to MLB_Scrape.get_data,
called once per game as it finishes downloading (regardless of which
order they complete in, via ThreadPoolExecutor's as_completed), and
threaded it through get_batter_pitch_log / get_pitcher_pitch_log /
get_team_pitch_log as a second, separate parameter alongside the existing
text-only progress_callback — so no existing caller's behavior changes,
this only adds a new, optional hook. The Batter/Pitcher/Team Dashboards
use it to drive a real st.progress() bar during the actual games-loading
step.
"""
import pandas as pd

import api_scraper
import data_layer


def test_get_data_calls_game_progress_callback_once_per_game():
    scraper = api_scraper.MLB_Scrape()

    def fake_requests_get(url, **kwargs):
        class FakeResp:
            def json(self):
                return {"gamePk": 1}
        return FakeResp()

    api_scraper.requests.get = fake_requests_get

    calls = []
    result = scraper.get_data(game_list_input=[100, 101, 102, 103, 104],
                               game_progress_callback=lambda c, t: calls.append((c, t)))
    assert len(result) == 5
    assert len(calls) == 5
    assert all(total == 5 for _, total in calls)
    assert sorted(c for c, _ in calls) == [1, 2, 3, 4, 5]
    print("MLB_Scrape.get_data: game_progress_callback fires exactly once per game, correct totals")


def test_get_data_without_callback_still_works():
    """Backward compatibility: every existing call site that doesn't pass
    the new parameter at all must be completely unaffected."""
    scraper = api_scraper.MLB_Scrape()

    def fake_requests_get(url, **kwargs):
        class FakeResp:
            def json(self):
                return {"gamePk": 1}
        return FakeResp()

    api_scraper.requests.get = fake_requests_get
    result = scraper.get_data(game_list_input=[100, 101, 102])
    assert len(result) == 3
    print("MLB_Scrape.get_data: works identically when game_progress_callback is omitted")


def test_pitch_log_functions_thread_game_progress_callback_through():
    def fake_get_data(game_list_input, game_progress_callback=None):
        if game_progress_callback:
            for i in range(len(game_list_input)):
                game_progress_callback(i + 1, len(game_list_input))
        return []

    fake_df = pd.DataFrame({
        "game_id": [1, 1], "game_date": ["2026-04-01"] * 2, "ab_number": [0, 1],
        "batter_id": [1, 1], "pitcher_id": [1, 1], "pitcher_name": ["Test", "Test"],
        "event_type": ["single", None], "batter_team_id": [136, 136], "pitcher_team_id": [133, 133],
    })

    data_layer.scraper.get_data = fake_get_data
    data_layer.scraper.get_player_games_list = lambda **kwargs: [1, 2, 3]
    data_layer.scraper.get_data_df = lambda data_list: fake_df.copy()

    for name, func, kwargs in [
        ("get_batter_pitch_log", data_layer.get_batter_pitch_log,
         dict(player_id=1, player_name="Test", season=2026, sport_id=1)),
        ("get_pitcher_pitch_log", data_layer.get_pitcher_pitch_log,
         dict(player_id=1, player_name="Test", season=2026, sport_id=1)),
    ]:
        calls = []
        func(**kwargs, force_refresh=True, game_progress_callback=lambda c, t: calls.append((c, t)))
        assert calls == [(1, 3), (2, 3), (3, 3)], f"{name}: {calls}"

    fake_sched = pd.DataFrame({"game_id": [1, 2, 3], "game_date": ["2026-04-01"] * 3,
                                "home_id": [136] * 3, "away_id": [133] * 3})
    data_layer.get_schedule_lookup = lambda season, sport_id, force_refresh=False: fake_sched.copy()
    calls = []
    data_layer.get_team_pitch_log(team_id=136, team_name="Test Team", season=2026, sport_id=1,
                                    force_refresh=True, game_progress_callback=lambda c, t: calls.append((c, t)))
    assert calls == [(1, 3), (2, 3), (3, 3)]

    print("get_batter_pitch_log / get_pitcher_pitch_log / get_team_pitch_log:")
    print("  game_progress_callback correctly threaded through to scraper.get_data in all three")


def test_pitch_log_functions_without_game_progress_callback_still_work():
    """Backward compatibility for data_layer's own existing callers too —
    omitting the new parameter entirely must not break anything."""
    def fake_get_data(game_list_input, game_progress_callback=None):
        return []

    fake_df = pd.DataFrame({
        "game_id": [1], "game_date": ["2026-04-01"], "ab_number": [0],
        "batter_id": [1], "pitcher_id": [1], "pitcher_name": ["Test"], "event_type": ["single"],
        "batter_team_id": [136], "pitcher_team_id": [133],
    })
    data_layer.scraper.get_data = fake_get_data
    data_layer.scraper.get_player_games_list = lambda **kwargs: [1]
    data_layer.scraper.get_data_df = lambda data_list: fake_df.copy()

    result = data_layer.get_batter_pitch_log(player_id=1, player_name="Test", season=2026, sport_id=1,
                                               force_refresh=True)
    assert result is not None
    print("get_batter_pitch_log: works identically when game_progress_callback is omitted")


def test_batter_dashboard_progress_bar_ui_wiring():
    """End-to-end: st.progress() should render without exceptions when
    game_progress_callback actually fires during a real load, through the
    full rendered page — not just the underlying data flow tested above."""
    import numpy as np
    from test_smoke import df as synthetic_df

    fake_universe = pd.DataFrame([
        {"player_id": 123456, "name": "Test Batter", "position": "OF", "team": "Seattle Mariners",
         "sport_id": 1, "level": "MLB", "display_name": "Test Batter  —  MLB"},
    ])
    data_layer.load_player_universe = lambda season, force_refresh=False: fake_universe.copy()

    def fake_get_batter_pitch_log(player_id, player_name, season, sport_id, force_refresh=False,
                                    progress_callback=None, game_progress_callback=None):
        if progress_callback:
            progress_callback("Pulling pitch-by-pitch data for 3 games…")
        if game_progress_callback:
            for i in range(1, 4):
                game_progress_callback(i, 3)
        return synthetic_df.copy()

    data_layer.get_batter_pitch_log = fake_get_batter_pitch_log
    data_layer.attach_home_away = lambda df, season, sport_id: df.assign(
        is_home=np.random.choice([True, False], size=len(df))
    )
    data_layer.get_standard_leaderboard = (
        lambda season, sport_id, force_refresh=False, start_date=None, end_date=None:
        pd.DataFrame({"avg": [.25] * 10, "obp": [.32] * 10, "slg": [.4] * 10, "ops": [.7] * 10,
                       "k_pct": [.2] * 10, "bb_pct": [.08] * 10, "qualified": True})
    )
    data_layer.get_savant_percentile_pool = lambda season, force_refresh=False: pd.DataFrame()
    data_layer.get_qualified_pa_threshold = lambda season, sport_id: 300

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file("views/batter_dashboard.py", default_timeout=60)
    at.run()
    player_sb = [sb for sb in at.selectbox if sb.label == "Player"][0]
    player_sb.select_index(0)
    at.run()
    [b for b in at.button if b.label == "Load batter"][0].click()
    at.run()
    assert not at.exception, f"Exception during load with progress bar: {list(at.exception)}"
    print("Batter Dashboard: st.progress() wiring renders correctly through a full load, no exceptions")


if __name__ == "__main__":
    test_get_data_calls_game_progress_callback_once_per_game()
    test_get_data_without_callback_still_works()
    test_pitch_log_functions_thread_game_progress_callback_through()
    test_pitch_log_functions_without_game_progress_callback_still_work()
    test_batter_dashboard_progress_bar_ui_wiring()
    print("\nALL PROGRESS-BAR REGRESSION TESTS PASSED")
