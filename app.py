"""
Entry point. Run with:  streamlit run app.py

This file is only a navigation router — it sets the page config once (must
happen exactly once, before anything else) and declares the three views with
explicit titles, so the nav reads "Batter" / "Pitcher" / "Team" instead of a
raw filename. Rendered as a horizontal tab-style bar at the top of the page
(position="top") rather than the sidebar, since the sidebar is used for each
page's own player/team search controls instead. The actual page content
lives in views/.
"""

import streamlit as st

st.set_page_config(page_title="MLB Analytics", layout="wide", initial_sidebar_state="expanded")

batter_page = st.Page("views/batter_dashboard.py", title="Batter", default=True)
pitcher_page = st.Page("views/pitcher_dashboard.py", title="Pitcher")
team_page = st.Page("views/team_dashboard.py", title="Team")

nav = st.navigation([batter_page, pitcher_page, team_page], position="top")
nav.run()
