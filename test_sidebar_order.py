"""
Regression test for the requested sidebar reorder: Player/Team search
should render first (before Season/Levels), even though the search box's
own options depend on season/level. This works by reading each filter's
CURRENT value from st.session_state before its own widget renders later
in the script — Streamlit persists widget values across reruns under
their key, so this reflects whatever was last picked, and correctly
cascades to the search box above it on the next rerun after a change.

Two things worth covering directly: (1) the elements actually render in
the requested order, not just "doesn't crash", and (2) changing a filter
actually narrows the search box's options on the next run — proving the
session-state pre-read pattern really cascades, not just renders once
with its fallback defaults.
"""
import numpy as np
import pandas as pd

import data_layer
from test_smoke import df as synthetic_df  # noqa: E402 (re-executes test_smoke's own prints, harmless)


def test_batter_sidebar_order():
    fake_universe = pd.DataFrame([
        {"player_id": 1, "name": "Test Batter", "position": "OF", "team": "Seattle Mariners",
         "sport_id": 1, "level": "MLB", "display_name": "Test Batter  —  MLB"},
    ])
    data_layer.load_player_universe = lambda season, force_refresh=False: fake_universe.copy()
    data_layer.get_batter_pitch_log = lambda **kwargs: synthetic_df.copy()

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file("views/batter_dashboard.py", default_timeout=60)
    at.run()
    assert not at.exception, f"Exception: {list(at.exception)}"

    order = [type(el).__name__ for el in at.sidebar
             if type(el).__name__ in ("Selectbox", "NumberInput", "ButtonGroup")]
    assert order.index("Selectbox") < order.index("NumberInput") < order.index("ButtonGroup"), \
        f"expected Player search, then Season, then Levels — got {order}"
    print("Batter sidebar order: Player search -> Season -> Levels, as requested")


def test_batter_sidebar_cascading():
    fake_universe = pd.DataFrame([
        {"player_id": 1, "name": "MLB Batter", "position": "OF", "team": "Seattle Mariners",
         "sport_id": 1, "level": "MLB", "display_name": "MLB Batter  —  MLB"},
        {"player_id": 2, "name": "AAA Batter", "position": "OF", "team": "Tacoma Rainiers",
         "sport_id": 11, "level": "AAA", "display_name": "AAA Batter  —  AAA"},
    ])
    data_layer.load_player_universe = lambda season, force_refresh=False: fake_universe.copy()
    data_layer.get_batter_pitch_log = lambda **kwargs: synthetic_df.copy()

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file("views/batter_dashboard.py", default_timeout=60)
    at.run()
    assert not at.exception

    player_sb = [sb for sb in at.selectbox if sb.label == "Player"][0]
    assert len(player_sb.options) == 2, "expected both levels represented before narrowing"

    level_pills = [p for p in at.pills if p.key == "bat_level_pills"][0]
    level_pills.set_value(["MLB"])
    at.run()
    assert not at.exception, f"Exception after narrowing levels: {list(at.exception)}"

    player_sb2 = [sb for sb in at.selectbox if sb.label == "Player"][0]
    assert len(player_sb2.options) == 1, \
        "narrowing Levels (rendered AFTER Player search) should still narrow the Player options above it"
    print("Batter sidebar cascading: narrowing Levels correctly narrows Player search on the next run")


if __name__ == "__main__":
    test_batter_sidebar_order()
    test_batter_sidebar_cascading()
    print("\nALL SIDEBAR ORDER REGRESSION TESTS PASSED")
