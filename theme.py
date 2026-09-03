"""
theme.py
────────
Shared visual styling for all three pages. Keeping this in one place means a
tweak here shows up everywhere instead of drifting between three copy-pasted
<style> blocks.

Palette: "Deep Jewel Tones" (one of six documented dark-mode palettes from
vev.design/blog/dark-mode-website-color-palette) — rich black background,
off-white text, teal / ruby / forest-green as the three jewel accents. The
three pages each take one: Batter=teal, Pitcher=ruby, Team=forest green.
The base hex values from that palette (#1A1A1A bg, #F0F0F0 text) are used as-
is; the three accent jewel tones are brightened from their documented values
since the original hex codes (e.g. #822659) are calibrated for large surface
areas, not a 1-2px UI accent that needs to read clearly against a near-black
background.
"""

import streamlit as st

BG = "#1a1a1a"
BG_SIDEBAR = "#161616"
BORDER = "#333333"
TEXT_PRIMARY = "#f0f0f0"
TEXT_MUTED = "#9a9a9a"

ACCENTS = {
    "batter": "#2f9bb5",   # teal
    "pitcher": "#c2447a",  # ruby
    "team": "#5a9169",     # forest green
}

LEVEL_COLORS = {
    "MLB": "#2f9bb5",
    "AAA": "#9b7fd4",
    "AA": "#c2447a",
    "High-A": "#d4a24a",
    "A": "#5a9169",
}


def inject_theme(accent: str = "#2f9bb5") -> None:
    """Call once near the top of a page. Layers refinements on top of the
    dark theme already set in .streamlit/config.toml. Flat and typographic
    rather than boxed — no card borders or colored side-bars on metric
    tiles; a stat reads as a stat, not a widget."""
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        html, body, [class*="css"], .stMarkdown, .stText {{
            font-family: 'Inter', -apple-system, sans-serif;
        }}

        .stApp {{ background-color: {BG}; }}
        section[data-testid="stSidebar"] {{
            background-color: {BG_SIDEBAR};
            border-right: 1px solid {BORDER};
        }}

        /* Metric tiles — plain typography, no box/border/left-bar. A thin
           bottom rule separates rows the way a stat table would. */
        div[data-testid="stMetric"] {{
            background: transparent;
            border: none;
            border-bottom: 1px solid {BORDER};
            border-radius: 0;
            padding: 6px 10px 10px 2px;
        }}
        div[data-testid="stMetricLabel"] p {{
            color: {TEXT_MUTED} !important;
            font-size: 12px !important;
            font-weight: 600 !important;
            letter-spacing: 0.4px;
            text-transform: uppercase;
        }}
        div[data-testid="stMetricValue"] {{
            color: {TEXT_PRIMARY} !important;
            font-weight: 700 !important;
        }}

        /* Headings */
        h1, h2, h3 {{ color: {TEXT_PRIMARY} !important; font-weight: 700 !important; }}
        h2 {{ border-bottom: 1px solid {BORDER}; padding-bottom: 6px; margin-top: 24px !important; }}

        /* Tabs */
        .stTabs [data-baseweb="tab"] {{
            color: {TEXT_MUTED}; font-weight: 600; font-size: 14px;
        }}
        .stTabs [aria-selected="true"] {{ color: {accent} !important; }}
        .stTabs [data-baseweb="tab-highlight"] {{ background-color: {accent} !important; }}
        .stTabs [data-baseweb="tab-border"] {{ background-color: {BORDER} !important; }}

        /* Buttons */
        .stButton > button[kind="primary"] {{
            background-color: {accent}; border: none; font-weight: 600;
        }}
        .stButton > button[kind="primary"]:hover {{ opacity: 0.88; }}

        /* Bordered containers (st.container(border=True)) */
        div[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius: 6px !important; }}

        /* Misc */
        hr {{ border-color: {BORDER} !important; }}
        div[data-testid="stExpander"] {{
            border: 1px solid {BORDER}; border-radius: 6px; background-color: #1e1e1e;
        }}
        .stDataFrame {{ border-radius: 6px; overflow: hidden; }}

        /* ── Mobile (phone-width screens) ──────────────────────────────────
           Streamlit's st.columns() never reflows on its own — a 6-column
           stat-tile row or a 2-chart side-by-side row just gets squeezed
           into whatever width is available, which on a ~375-430px phone
           screen makes both unreadable. Below 640px, force every column
           row in the app to stack into a single column instead: more
           scrolling, but everything stays full-width and legible. Plotly
           charts (rendered with width='stretch') automatically fill
           whatever width their container ends up with, so they benefit
           from this without any chart-specific changes.

           Exception: metric-tile rows specifically (detected via :has() —
           does this row contain a stMetric) wrap into ~3-per-row instead
           of fully stacking, since a full stack of 12 individual stat
           tiles meant scrolling through 12 rows just to see the headline
           numbers. :has() needs a reasonably modern browser (Chrome/Edge
           105+, Safari 15.4+, Firefox 121+) — effectively any phone
           browser that's auto-updated in the last couple of years. */
        @media (max-width: 640px) {{
            div[data-testid="stHorizontalBlock"] {{
                flex-direction: column !important;
            }}
            div[data-testid="stColumn"] {{
                width: 100% !important;
                flex: 1 1 100% !important;
                min-width: 100% !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(div[data-testid="stMetric"]) {{
                flex-direction: row !important;
                flex-wrap: wrap !important;
                gap: 4px !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(div[data-testid="stMetric"]) > div[data-testid="stColumn"] {{
                width: auto !important;
                min-width: 31% !important;
                flex: 1 1 31% !important;
            }}
            div[data-testid="stMetric"] {{ padding: 4px 6px 8px 2px !important; }}
            div[data-testid="stMetricValue"] {{ font-size: 1.25rem !important; }}
            div[data-testid="stMetricLabel"] p {{ font-size: 10px !important; }}

            /* Only reclaim the side margins here — Streamlit's own
               top padding on .block-container is sized to clear its
               fixed header bar; overriding it made the header cover the
               page title instead. Left/right have no such dependency. */
            .block-container {{
                padding-left: 1rem !important;
                padding-right: 1rem !important;
            }}
            .pageTitle {{ font-size: 22px !important; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str, accent: str, badge: str = None) -> None:
    """A plain header — bold title, one muted line of context, optional
    level badge. No box, no colored bar — just type, the way a Savant
    player page leads with the name and nothing else."""
    badge_html = ""
    if badge:
        badge_color = LEVEL_COLORS.get(badge, accent)
        badge_html = (
            f'<span style="background:{badge_color}1a; color:{badge_color}; '
            f'border:1px solid {badge_color}55; padding:1px 9px; border-radius:4px; '
            f'font-size:12px; font-weight:600; margin-left:9px;">{badge}</span>'
        )
    st.markdown(
        f"""
        <div style="margin-bottom:14px;">
            <div class="pageTitle" style="font-size:28px; font-weight:700; color:{TEXT_PRIMARY}; line-height:1.2;">
                {title}{badge_html}
            </div>
            <div style="font-size:13px; color:{TEXT_MUTED}; margin-top:2px;">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_title(text: str, accent: str) -> None:
    """A slightly more styled alternative to st.subheader() with a colored
    accent dot, used for major section breaks within a page."""
    st.markdown(
        f'<div style="display:flex; align-items:center; gap:8px; margin:4px 0 2px 0;">'
        f'<div style="width:7px; height:7px; border-radius:50%; background:{accent};"></div>'
        f'<div style="font-size:18px; font-weight:700; color:{TEXT_PRIMARY};">{text}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def compact_stat_row(pairs) -> None:
    """A smaller, denser companion row for counting stats (H, HR, RBI, etc)
    that don't need the same visual weight as the primary rate-stat tiles —
    just label:value pairs in a single line, wrapping as needed."""
    items = "".join(
        f'<div style="white-space:nowrap;">'
        f'<span style="color:{TEXT_MUTED}; font-size:12px; font-weight:600; text-transform:uppercase; '
        f'letter-spacing:0.3px;">{label}</span> '
        f'<span style="color:{TEXT_PRIMARY}; font-size:14px; font-weight:700;">{value}</span>'
        f"</div>"
        for label, value in pairs
    )
    st.markdown(
        f'<div style="display:flex; flex-wrap:wrap; gap:18px; padding:6px 2px 14px 2px; '
        f'border-bottom:1px solid {BORDER}; margin-bottom:14px;">{items}</div>',
        unsafe_allow_html=True,
    )
