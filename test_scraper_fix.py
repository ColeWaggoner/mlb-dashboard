"""
Regression test for a real data bug found via a user report (Lazaro Montes'
AAA slash line showing lower than official sources despite matching games
played): api_scraper.get_data_df was silently dropping any plate appearance
whose chronologically LAST recorded playEvent wasn't itself a pitch (e.g. a
baserunning/defensive event MLB logs after the batter's decisive pitch) —
the actual outcome (hit/out/walk/etc) only ever gets attached to that last
event's row, so if that row got excluded, the whole PA vanished from AVG/
OBP/SLG even though the game and its other at-bats still counted normally.

This builds a minimal synthetic game reproducing exactly that pattern and
confirms every at-bat's outcome now survives into the dataframe.
"""
import sys

import pandas as pd

from api_scraper import MLB_Scrape

scraper = MLB_Scrape()


def make_pitch_event(pitch_num, code, is_in_play=False, balls=0, strikes=0):
    return {
        "isPitch": True,
        "pitchNumber": pitch_num,
        "details": {"code": code, "isInPlay": is_in_play, "isStrike": code in ("S", "C", "X")},
        "count": {"balls": balls, "strikes": strikes, "outs": 0},
    }


def make_matchup(batter_id, batter_name, bat_side, pitcher_id=10, pitcher_name="Pitcher One"):
    return {
        "batter": {"id": batter_id, "fullName": batter_name}, "batSide": {"code": bat_side},
        "pitcher": {"id": pitcher_id, "fullName": pitcher_name}, "pitchHand": {"code": "R"},
    }


game = {
    "gamePk": 999001,
    "gameData": {
        "datetime": {"officialDate": "2026-06-01"},
        "teams": {
            "home": {"abbreviation": "SEA", "id": 136},
            "away": {"abbreviation": "OAK", "id": 133},
        },
    },
    "liveData": {"plays": {"allPlays": [
        # Normal case: last playEvent IS a pitch — should already work either way.
        {
            "atBatIndex": 0, "about": {"isTopInning": True, "inning": 1},
            "matchup": make_matchup(1, "Batter One", "R"),
            "result": {"type": "atBat", "event": "Strikeout", "eventType": "strikeout", "rbi": 0,
                       "awayScore": 0, "homeScore": 0, "isOut": True},
            "playEvents": [make_pitch_event(1, "C", strikes=1), make_pitch_event(2, "S", strikes=2)],
        },
        # The bug case: single on pitch 2, but a non-pitch event (e.g. a
        # baserunning note) is appended last within this at-bat's playEvents.
        {
            "atBatIndex": 1, "about": {"isTopInning": True, "inning": 1},
            "matchup": make_matchup(2, "Batter Two", "L"),
            "result": {"type": "atBat", "event": "Single", "eventType": "single", "rbi": 0,
                       "awayScore": 0, "homeScore": 0, "isOut": False},
            "playEvents": [
                make_pitch_event(1, "B", balls=1),
                make_pitch_event(2, "X", is_in_play=True, balls=1),
                {"isPitch": False, "details": {}},  # <- triggers the bug pre-fix
            ],
        },
        # Normal case: a walk — should already work either way.
        {
            "atBatIndex": 2, "about": {"isTopInning": True, "inning": 1},
            "matchup": make_matchup(3, "Batter Three", "R"),
            "result": {"type": "atBat", "event": "Walk", "eventType": "walk", "rbi": 0,
                       "awayScore": 0, "homeScore": 0, "isOut": False},
            "playEvents": [make_pitch_event(i, "B", balls=i) for i in range(1, 5)],
        },
        # A second bug case, this time the dropped PA is a home run — checks
        # the fix isn't specific to singles/in-play-boolean quirks.
        {
            "atBatIndex": 3, "about": {"isTopInning": True, "inning": 2},
            "matchup": make_matchup(1, "Batter One", "R"),
            "result": {"type": "atBat", "event": "Home Run", "eventType": "home_run", "rbi": 1,
                       "awayScore": 1, "homeScore": 0, "isOut": False},
            "playEvents": [
                make_pitch_event(1, "X", is_in_play=True, balls=0),
                {"isPitch": False, "details": {}},
            ],
        },
    ]}},
}

data_df = scraper.get_data_df(data_list=[game])
df = data_df.to_pandas() if hasattr(data_df, "to_pandas") else data_df

pa_rows = df[df["event_type"].notna()]
print("Rows with a populated event_type:", len(pa_rows))
print(pa_rows[["ab_number", "batter_name", "event_type"]].to_string())

expected_events = {"strikeout", "single", "walk", "home_run"}
found_events = set(pa_rows["event_type"].tolist())

assert len(pa_rows) == 4, f"expected 4 plate appearances, got {len(pa_rows)}"
assert found_events == expected_events, f"missing events: {expected_events - found_events}"

print("\nSCRAPER FIX REGRESSION TEST PASSED — no plate appearances dropped.")


# ─────────────────────────────────────────────────────────────────────────────
# Second regression: duplicate game_ids should not double-count plate
# appearances. Diagnosed from a Baseball Reference comparison showing counts
# running slightly HIGH (extra PA/AB), the opposite signature from the
# dropped-plate-appearance bug above.
# ─────────────────────────────────────────────────────────────────────────────
import data_layer  # noqa: E402

GAME_PA_MAP = {
    500: [(0, "strikeout"), (1, "single")],
    501: [(0, "walk"), (1, "single")],
    502: [(0, "strikeout")],
}


class _FakeGameDataDF:
    def __init__(self, game_ids):
        self.game_ids = game_ids

    def to_pandas(self):
        rows = []
        for gid in self.game_ids:  # mirrors real get_data: iterates whatever list it received
            for ab, event in GAME_PA_MAP[gid]:
                rows.append({
                    "game_id": gid, "game_date": "2026-06-01", "ab_number": ab, "index_play": 0,
                    "batter_id": 1, "batter_name": "Test Batter", "event_type": event,
                    "pitch_description": "Four-Seam Fastball", "is_swing": True, "is_whiff": None,
                    "in_play": event == "single", "rbi": 0,
                })
        return pd.DataFrame(rows)


data_layer.scraper.get_player_games_list = lambda **kwargs: [500, 501, 501, 502]  # 501 duplicated
data_layer.scraper.get_data = lambda game_list_input: game_list_input
data_layer.scraper.get_data_df = lambda data_list: _FakeGameDataDF(data_list)

dup_test_df = data_layer.get_batter_pitch_log(
    player_id=1, player_name="Test Batter", season=2026, sport_id=11, force_refresh=True,
)
n_pa_recovered = dup_test_df["event_type"].notna().sum()
n_unique_games = dup_test_df["game_id"].nunique()

print(f"\nDuplicate-game test: {n_unique_games} unique games, {n_pa_recovered} plate appearances")
assert n_unique_games == 3, f"expected 3 unique games (500,501,502), got {n_unique_games}"
assert n_pa_recovered == 5, f"expected 5 PA total (2+2+1), got {n_pa_recovered} — duplication not prevented"

print("DUPLICATE-GAME REGRESSION TEST PASSED — repeated game_id did not double-count plate appearances.")


# ─────────────────────────────────────────────────────────────────────────────
# Third regression: non-atBat "action" plays (caught stealing, pickoffs,
# stolen bases, mound visits, etc.) must never generate a plate-appearance
# row, even though they have their own entry in allPlays and can reference
# a batter. This was the actual remaining cause of counts still running
# high after the dedup fix above — the dropped-PA fix (regression #1) was
# too broad and let an action play's trailing event slip through as if it
# were a real at-bat outcome.
# ─────────────────────────────────────────────────────────────────────────────
def make_matchup_action(batter_id, batter_name, bat_side="R"):
    return {
        "batter": {"id": batter_id, "fullName": batter_name}, "batSide": {"code": bat_side},
        "pitcher": {"id": 10, "fullName": "Pitcher One"}, "pitchHand": {"code": "R"},
    }


action_play_game = {
    "gamePk": 999003,
    "gameData": {
        "datetime": {"officialDate": "2026-06-01"},
        "teams": {
            "home": {"abbreviation": "SEA", "id": 136},
            "away": {"abbreviation": "OAK", "id": 133},
        },
    },
    "liveData": {"plays": {"allPlays": [
        # A real at-bat first.
        {
            "atBatIndex": 0, "about": {"isTopInning": True, "inning": 1},
            "matchup": make_matchup_action(2, "Batter Two"),
            "result": {"type": "atBat", "event": "Single", "eventType": "single", "rbi": 0,
                       "awayScore": 0, "homeScore": 0, "isOut": False},
            "playEvents": [make_pitch_event(1, "X", is_in_play=True, balls=0)],
        },
        # Then a standalone caught-stealing "action" play — not a real PA.
        {
            "about": {"isTopInning": True, "inning": 1},
            "matchup": make_matchup_action(2, "Batter Two"),
            "result": {"type": "action", "event": "Caught Stealing 2B", "eventType": "caught_stealing_2b",
                       "rbi": 0, "awayScore": 0, "homeScore": 0, "isOut": True},
            "playEvents": [{"isPitch": False, "details": {}}],
        },
    ]}},
}

action_df = scraper.get_data_df(data_list=[action_play_game])
action_pdf = action_df.to_pandas() if hasattr(action_df, "to_pandas") else action_df
action_pa_rows = action_pdf[action_pdf["event_type"].notna()]

print(f"\nAction-play test: {len(action_pa_rows)} PA row(s), events: {set(action_pa_rows['event_type'])}")
assert len(action_pa_rows) == 1, f"expected exactly 1 real PA (the single), got {len(action_pa_rows)}"
assert "caught_stealing_2b" not in set(action_pa_rows["event_type"]), \
    "the caught-stealing action play was wrongly counted as a plate appearance"

print("ACTION-PLAY REGRESSION TEST PASSED — non-atBat plays never counted as a plate appearance.")


# ─────────────────────────────────────────────────────────────────────────────
# Fourth regression: found from a user-supplied real raw-data export (Lazaro
# Montes, 2026 AAA). Two distinct bugs were hiding in that one discrepancy:
# 1. 'caught_stealing_2b' rows (a baserunning out attached to the batter's
#    at-bat entry, result.type=='atBat' — NOT caught by the action-play fix
#    above, which only excludes result.type=='action') were still being
#    counted as both a plate appearance AND an at-bat.
# 2. 'intent_walk' was never recognized as a walk (only exact-matched
#    "walk"), so it fell through and got counted as an at-bat instead of
#    being excluded like a regular walk.
# Together these accounted for the exact reported gap: 205->203 PA,
# 178->175 AB, 24->25 BB — verified against the real CSV, not just a
# synthetic reproduction, but this test pins the mechanism down directly.
# ─────────────────────────────────────────────────────────────────────────────
import stats  # noqa: E402

real_bug_df = pd.DataFrame([
    {"event_type": "strikeout"},
    {"event_type": "single"},
    {"event_type": "field_out"},
    {"event_type": "walk"},
    {"event_type": "intent_walk"},       # bug 2: must count as a walk, not an AB
    {"event_type": "caught_stealing_2b"},  # bug 1: must not count as PA or AB at all
    {"event_type": "caught_stealing_2b"},
])

slash = stats.compute_slash_line(real_bug_df)
print(f"\nReal-bug regression: PA={slash['n_pa']}, AB={slash['n_ab']}, BB={slash['n_bb']}")
assert slash["n_pa"] == 5, f"expected 5 real PA (2 caught_stealing rows excluded), got {slash['n_pa']}"
assert slash["n_ab"] == 3, f"expected 3 AB (strikeout, single, field_out), got {slash['n_ab']}"
assert slash["n_bb"] == 2, f"expected 2 BB (walk + intent_walk), got {slash['n_bb']}"

print("REAL-DATA REGRESSION TEST PASSED — caught_stealing excluded from PA/AB, intent_walk counted as BB.")
