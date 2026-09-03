"""
Entry point. Run with:  streamlit run app.py

This file is only a navigation router — it sets the page config once (must
happen exactly once, before anything else) and declares the three views with
explicit titles, so the sidebar nav reads "Batter Dashboard" / "Pitcher
Dashboard" / "Team Dashboard" instead of a raw filename. The actual page
content lives in views/.
"""

import streamlit as st

st.set_page_config(page_title="MLB Analytics", layout="wide", initial_sidebar_state="expanded")

batter_page = st.Page("views/batter_dashboard.py", title="Batter Dashboard", default=True)
pitcher_page = st.Page("views/pitcher_dashboard.py", title="Pitcher Dashboard")
team_page = st.Page("views/team_dashboard.py", title="Team Dashboard")

nav = st.navigation([batter_page, pitcher_page, team_page])
nav.run()
