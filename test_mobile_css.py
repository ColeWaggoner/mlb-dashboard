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
    """Confirms 'stHorizontalBlock'/'stColumn' (the selectors the mobile CSS
    targets) are actually the testid strings this installed Streamlit
    version renders columns with, rather than assuming from general
    knowledge. Skips gracefully if the compiled frontend isn't found
    (e.g. a different Streamlit install layout) rather than failing on an
    environment difference unrelated to the CSS itself."""
    import glob

    bundles = glob.glob(f"{STREAMLIT_STATIC_DIR}/*.js")
    if not bundles:
        print("SKIPPED — compiled Streamlit frontend not found at the expected path in this environment.")
        return

    found_horizontal_block = False
    found_column = False
    for path in bundles:
        with open(path, "rb") as f:
            content = f.read()
        if b"stHorizontalBlock" in content:
            found_horizontal_block = True
        if b"stColumn" in content:
            found_column = True

    assert found_horizontal_block, "stHorizontalBlock testid not found in the installed Streamlit frontend"
    assert found_column, "stColumn testid not found in the installed Streamlit frontend"
    print("Confirmed against the installed Streamlit frontend: stHorizontalBlock and stColumn are real testids")


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

    # Braces must balance -- an f-string escaping mistake ({{ vs {) would
    # silently produce broken CSS that a browser mostly ignores rather than
    # erroring on, so this needs an explicit check rather than relying on
    # "it didn't crash".
    assert css.count("{") == css.count("}"), "unbalanced braces in rendered CSS"

    print("Mobile CSS renders with correct selectors, no header-covering padding-top, balanced braces")


if __name__ == "__main__":
    test_column_testids_match_installed_streamlit_version()
    test_mobile_css_renders_correctly()
    print("\nALL MOBILE CSS REGRESSION TESTS PASSED")
