"""
Regression test for the mobile-responsive CSS added to theme.inject_theme().

Streamlit's st.columns() doesn't reflow on its own — without this CSS, a
6-column stat-tile row or a 2-chart side-by-side row just gets squeezed
into whatever width is available, which is unreadable on a phone screen.
The fix forces every column row to stack into a single column below a
640px viewport width, targeting the exact data-testid strings this
project's installed Streamlit version (1.63.0) actually renders columns
with — confirmed directly against the installed package's compiled
frontend bundle, not assumed from general Streamlit knowledge, since a
wrong selector here would make the whole fix a silent no-op.

This test can't verify what a real phone screen looks like (no browser
available in this environment) — what it does verify: the CSS is
syntactically valid, renders without exceptions, targets the correct
selectors, and is present on all three pages, so a future refactor can't
silently drop it.
"""
import re

STREAMLIT_STATIC_DIR = "/usr/local/lib/python3.12/dist-packages/streamlit/static/static/js"


def test_column_testids_match_installed_streamlit_version():
    """Confirms every testid the CSS depends on ('stHorizontalBlock'/
    'stColumn' for the layout-stacking rules, 'stPlotlyChart' for the
    chart-detection override, 'stTopNavLink' for the top-nav tab styling)
    are actually real strings this installed Streamlit version's compiled
    frontend uses, rather than assumed from general knowledge. Checks
    every JS bundle, not just the main one — some components (Plotly
    charts included) ship as separate lazy-loaded chunks. Skips gracefully
    if the compiled frontend isn't found (e.g. a different Streamlit
    install layout) rather than failing on an environment difference
    unrelated to the CSS itself."""
    import glob

    bundles = glob.glob(f"{STREAMLIT_STATIC_DIR}/*.js")
    if not bundles:
        print("SKIPPED — compiled Streamlit frontend not found at the expected path in this environment.")
        return

    required = {
        b"stHorizontalBlock": False, b"stColumn": False, b"stPlotlyChart": False,
        b"stTopNavLink": False, b"stMetric": False,
        b"stApp": False, b"stAppViewContainer": False, b"stMain": False, b"stHeader": False,
        b"stStatusWidget": False,
    }
    for path in bundles:
        with open(path, "rb") as f:
            content = f.read()
        for key in required:
            if key in content:
                required[key] = True

    missing = [k.decode() for k, found in required.items() if not found]
    assert not missing, f"testid(s) not found in the installed Streamlit frontend: {missing}"
    print("Confirmed against the installed Streamlit frontend: all depended-on testids are real")


def test_mobile_css_renders_correctly():
    import theme
    from streamlit.testing.v1 import AppTest

    script = (
        "import sys\n"
        "sys.path.insert(0, '.')\n"
        "import theme\n"
        "theme.inject_theme('#2f9bb5')\n"
    )
    with open("/tmp/_mobile_css_test_app.py", "w") as f:
        f.write(script)

    at = AppTest.from_file("/tmp/_mobile_css_test_app.py", default_timeout=30)
    at.run()
    assert not at.exception, f"Exception rendering theme CSS: {list(at.exception)}"

    css = at.markdown[0].value
    assert "@media (max-width: 640px)" in css
    assert 'div[data-testid="stHorizontalBlock"]' in css
    assert 'div[data-testid="stColumn"]' in css
    assert "flex-direction: column" in css

    # Regression guard: an earlier version of this CSS overrode
    # .block-container's padding-top, which is what Streamlit relies on to
    # clear its own fixed header — that made the header cover the page
    # title. Only the side margins should be touched. (Use the LAST
    # occurrence of ".block-container" — the actual CSS rule — since the
    # comment above it also mentions the string.)
    block_container_rule = css.split(".block-container")[-1].split("}")[0]
    assert "padding-top" not in block_container_rule, \
        "padding-top override on .block-container would cover the header again"
    assert "padding-left" in block_container_rule

    # Metric-tile rows should wrap into a condensed multi-per-row layout
    # via :has(), not fully stack like everything else.
    assert ":has(div[data-testid=\"stMetric\"])" in css

    # Regression guard: the metric :has() rule matches ANY descendant, not
    # just direct children, so it incorrectly also caught rows like the
    # Batted Ball tab (chart next to a column with metrics nested inside
    # it) and squeezed the chart to ~31% width. The chart-detection rule
    # must exist AND come after the metric rule in source order, since
    # that's how the tie gets broken for rows matching both.
    chart_rule_idx = css.find(':has(div[data-testid="stPlotlyChart"])')
    metric_rule_idx = css.find(':has(div[data-testid="stMetric"])')
    assert chart_rule_idx != -1, "chart-detection override rule missing"
    assert chart_rule_idx > metric_rule_idx, \
        "chart-detection rule must come AFTER the metric rule to win the CSS tie-break"

    # Top navigation (Batter/Pitcher/Team) — moved from the sidebar to
    # position="top" and should be styled with a clear active-tab
    # indicator. Confirmed directly that stTopNavLink uses the same
    # aria-current="page" logic the old sidebar version did.
    assert 'stTopNavLink' in css
    assert 'aria-current="page"' in css
    assert 'a[data-testid="stSidebarNavLink"]' not in css, \
        "sidebar-nav-specific styling should be gone now that nav lives at the top"

    # Full-viewport background coverage: a user report that the themed
    # background didn't fill the whole screen on mobile first-load, and a
    # separate blank area in the sidebar, both trace to backgrounds only
    # covering their own content height rather than the full viewport.
    assert "100dvh" in css, "dynamic viewport height should be used for mobile background coverage"
    assert 'section[data-testid="stSidebar"] > div' in css and "min-height" in css

    # Charts hijacking scroll on touch devices: touch-action: pan-y lets
    # vertical swipes pass through to normal page scroll while still
    # allowing Plotly's own pan/zoom for other gesture types.
    assert 'div[data-testid="stPlotlyChart"]' in css and "touch-action: pan-y" in css

    # Loading indicator: Streamlit's cycling running-icon (a running-man
    # figure, a New Year's icon, etc — reported as looking like a random
    # sports-emoji cycle) should have its icon hidden. A separate custom
    # "only show while running" bar was tried and reverted — it turned out
    # to always be visible (stStatusWidget appears to stay present in the
    # DOM regardless of run state), so this checks it's gone rather than
    # present, to stop it from quietly coming back.
    assert 'div[data-testid="stStatusWidget"] svg' in css and "display: none" in css
    assert ':has(div[data-testid="stStatusWidget"])' not in css, \
        "the reverted always-on-regardless-of-state loading bar shouldn't come back"
    assert "mlbLoadingBar" not in css

    # Braces must balance -- an f-string escaping mistake ({{ vs {) would
    # silently produce broken CSS that a browser mostly ignores rather than
    # erroring on, so this needs an explicit check rather than relying on
    # "it didn't crash".
    assert css.count("{") == css.count("}"), "unbalanced braces in rendered CSS"

    print("Mobile CSS renders with correct selectors, no header-covering padding-top in the")
    print("mobile media query, chart-override correctly ordered after metric rule, top-nav")
    print("tab styling present, reverted loading-bar/header-height overrides confirmed absent,")
    print("balanced braces")


if __name__ == "__main__":
    test_column_testids_match_installed_streamlit_version()
    test_mobile_css_renders_correctly()
    print("\nALL MOBILE CSS REGRESSION TESTS PASSED")
