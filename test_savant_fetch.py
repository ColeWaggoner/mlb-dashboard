"""
Regression tests for a live-deployment bug report: Baseball Savant's CSV
leaderboard export was returning the plain HTML leaderboard page instead
of CSV data, breaking every Statcast percentile row (Hard-Hit%, Avg Exit
Velo, Chase%, Whiff%, Sweet-Spot%). Same identical error persisted across
two rounds of header/session tuning, which is itself the important clue:
the request MECHANICS weren't the problem.

Root cause: this was using `/leaderboard/custom` — the interactive,
JavaScript-driven leaderboard BUILDER tool on Savant's site — with a
`csv=true` parameter that tool's server doesn't appear to act on at all
(its CSV export may be entirely client-side JS working from already-
loaded page data, rather than a server-side response to that URL
parameter). No header tuning could ever have fixed that, since the URL
itself wasn't the right one for a server-side CSV response.

Fixed by switching to `/leaderboard/statcast` — a different, older,
simpler endpoint, verified against pybaseball's actual public source code
(a real, widely-used, actively-maintained library whose own batted-ball
leaderboard functions depend on this exact URL working). That endpoint is
specifically the classic batted-ball-quality leaderboard, so it covers
Hard-Hit%/Avg Exit Velo/Sweet-Spot% but not Chase%/Whiff% (those live on
Savant's separate "Swing & Take" leaderboard, independently documented
elsewhere as currently broken on Baseball Savant's own end — a different,
actively-maintained package's "Known Issues" section documents that exact
CSV export returning headers with no data rows). Chase%/Whiff% percentile
comparisons are consequently not available from Savant right now
regardless of what this app does — they gracefully show no percentile
using the same mechanism already used for minor-league players (where
Statcast percentiles were never available at all).

The exact column names this endpoint returns still aren't independently
verified from this build environment, so SAVANT_METRICS hedges by mapping
two plausible naming conventions (the classic leaderboard's long-
established names, and the newer names this app was previously using) to
the same targets.

Update: after the endpoint fix above, a follow-up report showed a NEW
failure — Content-Type now correctly said text/csv (confirming the
endpoint fix worked and Savant was genuinely trying to return CSV), but
the body was garbled binary. Cause: this file's own prior header
improvements had added "br" (Brotli) to the Accept-Encoding header to
look more browser-realistic — but the optional brotli/brotlicffi package
isn't installed in this environment, so requests couldn't
auto-decompress a Brotli-compressed response, and the raw compressed
bytes got misread as UTF-8 text. Fixed by dropping "br" (back to
"gzip, deflate", which is requests' own actual default when this header
isn't set manually at all) and adding a specific diagnostic for this
exact failure shape (mostly-unprintable response body) so it's
immediately identifiable from the error message alone if it ever
recurs, rather than needing another round of detective work.
"""
import requests
import pandas as pd
import numpy as np

import data_layer
import stats


def test_savant_csv_fetch_makes_exactly_one_request():
    """Regression guard for a since-reverted 'warm-up' request — this
    should never silently creep back in."""
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)

        class FakeResp:
            text = "player_id,player_name,avg_hit_speed\n123,Test Player,90.0\n"
            status_code = 200
            headers = {"Content-Type": "text/csv; charset=utf-8"}

            def raise_for_status(self):
                pass

        return FakeResp()

    requests.get = fake_get
    data_layer._fetch_savant_csv("https://baseballsavant.mlb.com/leaderboard/statcast?year=2026&csv=true")
    assert len(calls) == 1, f"expected exactly 1 request (no warm-up), got {len(calls)}"
    print("Savant CSV fetch: makes exactly 1 request per call, no warm-up request")


def test_savant_csv_fetch_still_html_raises_clear_error():
    def fake_get(url, headers=None, timeout=None):
        class FakeResp:
            text = ('<!DOCTYPE html>\n<html lang="en_US">\n<head>\n'
                    "<title>Statcast Custom Leaderboards</title>")
            status_code = 200
            headers = {"Content-Type": "text/html; charset=utf-8"}

            def raise_for_status(self):
                pass

        return FakeResp()

    requests.get = fake_get
    try:
        data_layer._fetch_savant_csv("https://baseballsavant.mlb.com/leaderboard/statcast?year=2026&csv=true")
        raise AssertionError("expected a RuntimeError when Savant keeps returning HTML")
    except RuntimeError as e:
        assert "blocking automated requests" in str(e)
    print("Savant CSV fetch (still-HTML case): correctly raises the same clear diagnostic error")


def test_get_savant_percentile_pool_uses_correct_url():
    seen_urls = []

    def fake_get(url, headers=None, timeout=None):
        seen_urls.append(url)

        class FakeResp:
            text = "player_id,player_name,avg_hit_speed,ev95percent,anglesweetspotpercent\n123,P,91.5,42.3,35.1\n"
            status_code = 200
            headers = {"Content-Type": "text/csv; charset=utf-8"}

            def raise_for_status(self):
                pass

        return FakeResp()

    requests.get = fake_get
    data_layer.get_savant_percentile_pool(2026, force_refresh=True)
    url = seen_urls[-1]
    assert "leaderboard/statcast" in url, f"expected the verified-working endpoint, got {url}"
    assert "leaderboard/custom" not in url, "the broken /leaderboard/custom endpoint should never be used again"
    assert "type=batter" in url and "min=q" in url

    seen_urls.clear()
    data_layer.get_pitching_savant_percentile_pool(2026, force_refresh=True)
    url = seen_urls[-1]
    assert "leaderboard/statcast" in url and "type=pitcher" in url
    print("get_savant_percentile_pool / get_pitching_savant_percentile_pool: use the verified /leaderboard/statcast URL")


def test_column_mapping_classic_names():
    def fake_get(url, headers=None, timeout=None):
        class FakeResp:
            text = "player_id,player_name,avg_hit_speed,ev95percent,anglesweetspotpercent\n123,Test Player,91.5,42.3,35.1\n"
            status_code = 200
            headers = {"Content-Type": "text/csv; charset=utf-8"}

            def raise_for_status(self):
                pass

        return FakeResp()

    requests.get = fake_get
    result = data_layer.get_savant_percentile_pool(2026, force_refresh=True)
    assert set(["avg_ev", "hard_hit_pct", "sweet_spot_pct"]) <= set(result.columns)
    assert abs(result["avg_ev"].iloc[0] - 91.5) < 0.01
    assert abs(result["hard_hit_pct"].iloc[0] - 0.423) < 0.01
    assert abs(result["sweet_spot_pct"].iloc[0] - 0.351) < 0.01
    print("Column mapping (classic names: avg_hit_speed/ev95percent/anglesweetspotpercent): correct")


def test_column_mapping_alternate_names():
    def fake_get(url, headers=None, timeout=None):
        class FakeResp:
            text = "player_id,player_name,exit_velocity_avg,hard_hit_percent,sweet_spot_percent\n456,Alt,90.1,40.0,33.0\n"
            status_code = 200
            headers = {"Content-Type": "text/csv; charset=utf-8"}

            def raise_for_status(self):
                pass

        return FakeResp()

    requests.get = fake_get
    result = data_layer.get_savant_percentile_pool(2026, force_refresh=True)
    assert abs(result["avg_ev"].iloc[0] - 90.1) < 0.01
    assert abs(result["hard_hit_pct"].iloc[0] - 0.40) < 0.01
    assert abs(result["sweet_spot_pct"].iloc[0] - 0.33) < 0.01
    print("Column mapping (alternate names: exit_velocity_avg/hard_hit_percent/sweet_spot_percent): correct")


def test_column_mapping_both_variants_present_no_crash():
    """Edge case: if Savant's response ever contained BOTH naming
    conventions at once, the dict mapping two source names to the same
    target would otherwise produce genuine duplicate-named columns."""
    def fake_get(url, headers=None, timeout=None):
        class FakeResp:
            text = ("player_id,player_name,avg_hit_speed,exit_velocity_avg,ev95percent,hard_hit_percent,"
                    "anglesweetspotpercent,sweet_spot_percent\n789,Both,88.0,88.5,38.0,38.5,30.0,30.5\n")
            status_code = 200
            headers = {"Content-Type": "text/csv; charset=utf-8"}

            def raise_for_status(self):
                pass

        return FakeResp()

    requests.get = fake_get
    result = data_layer.get_savant_percentile_pool(2026, force_refresh=True)
    assert result.columns.tolist().count("avg_ev") == 1, "should dedupe to exactly one avg_ev column"
    assert result.columns.tolist().count("hard_hit_pct") == 1
    assert result.columns.tolist().count("sweet_spot_pct") == 1
    print("Both-naming-conventions-present edge case: correctly deduped, no crash")


def test_wrong_columns_raises_diagnostic_error():
    def fake_get(url, headers=None, timeout=None):
        class FakeResp:
            text = "totally_different_col,another_weird_name\nfoo,bar\n"
            status_code = 200
            headers = {"Content-Type": "text/csv; charset=utf-8"}

            def raise_for_status(self):
                pass

        return FakeResp()

    requests.get = fake_get
    try:
        data_layer.get_savant_percentile_pool(2026, force_refresh=True)
        raise AssertionError("expected a RuntimeError when no expected columns are present")
    except RuntimeError as e:
        assert "Actual columns received" in str(e)
        assert "totally_different_col" in str(e)
    print("Wrong-columns case: raises a clear diagnostic error showing the actual columns received")


def test_percentile_table_end_to_end():
    """Hard-Hit%/Avg Exit Velo/Sweet-Spot% should get real percentiles from
    the new Savant pool; Chase%/Whiff% should gracefully show no
    percentile (value still shown) rather than crash or show garbage,
    using the same mechanism already used for minor-league players."""
    savant_pool = pd.DataFrame({
        "player_id": range(50), "name": [f"P{i}" for i in range(50)],
        "avg_ev": np.random.uniform(85, 95, 50),
        "hard_hit_pct": np.random.uniform(0.2, 0.5, 50),
        "sweet_spot_pct": np.random.uniform(0.2, 0.4, 50),
    })
    standard_pool = pd.DataFrame({
        "avg": np.random.uniform(0.2, 0.3, 50), "obp": np.random.uniform(0.28, 0.38, 50),
        "slg": np.random.uniform(0.35, 0.5, 50), "ops": np.random.uniform(0.65, 0.9, 50),
        "k_pct": np.random.uniform(0.15, 0.3, 50), "bb_pct": np.random.uniform(0.05, 0.12, 50),
        "qualified": True,
    })
    player_stats = {
        "ba": 0.280, "obp": 0.350, "slg": 0.480, "ops": 0.830, "k_pct": 0.20, "bb_pct": 0.09,
        "hard_hit_pct": 0.40, "avg_ev": 91.0, "chase_pct": 0.28, "whiff_pct": 0.25, "sweet_spot_pct": 0.32,
    }
    table = stats.build_percentile_table(player_stats, standard_pool, savant_pool, is_mlb=True)

    for metric in ["Hard-Hit%", "Avg Exit Velo", "Sweet-Spot%"]:
        row = table[table["metric"] == metric].iloc[0]
        assert pd.notna(row["percentile"]), f"{metric} should have a percentile"
        assert row["source"] == "MLB Statcast (qualified)"

    for metric in ["Chase%", "Whiff%"]:
        row = table[table["metric"] == metric].iloc[0]
        assert pd.isna(row["percentile"]), f"{metric} should have no percentile (Savant data unavailable)"
        assert pd.isna(row["source"])
        assert pd.notna(row["value"]), f"{metric} should still show its own value"

    print("Percentile table end-to-end: Hard-Hit%/Avg EV/Sweet-Spot% have real percentiles,")
    print("Chase%/Whiff% gracefully show no percentile without crashing")


def test_no_brotli_in_accept_encoding():
    """Regression guard for a live-deployment report: this app's own
    earlier addition of 'br' (Brotli) to Accept-Encoding caused Savant to
    send a Brotli-compressed response that requests couldn't
    auto-decompress (the optional brotli/brotlicffi package isn't
    installed in this environment), producing garbled binary text instead
    of CSV. Should never advertise 'br' support again."""
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["headers"] = headers

        class FakeResp:
            text = "player_id,player_name\n1,Test\n"
            status_code = 200
            headers = {"Content-Type": "text/csv"}

            def raise_for_status(self):
                pass

        return FakeResp()

    requests.get = fake_get
    data_layer._fetch_savant_csv("https://baseballsavant.mlb.com/leaderboard/statcast?csv=true")
    accept_encoding = captured["headers"].get("Accept-Encoding", "")
    assert "br" not in accept_encoding.split(", "), f"'br' should never be advertised, got: {accept_encoding!r}"
    assert accept_encoding == "gzip, deflate"
    print("Accept-Encoding: correctly omits 'br', matches requests' own safe default")


def test_garbled_binary_response_gets_specific_diagnostic():
    """A response that decodes to mostly unprintable characters (what an
    undecompressed Brotli body looks like when misread as UTF-8 text)
    should raise an error that specifically names the likely cause,
    rather than the generic 'blocking automated requests' message that
    doesn't point anywhere useful for this particular failure mode."""
    garbled = bytes([0x1b, 0x2d, 0x73, 0x00, 0x48, 0x4e, 0x5a, 0x3d, 0x00, 0x1a] * 30).decode(
        "utf-8", errors="replace"
    )

    def fake_get(url, headers=None, timeout=None):
        class FakeResp:
            text = garbled
            status_code = 200
            headers = {"Content-Type": "text/csv; charset=utf-8", "Content-Encoding": "br"}

            def raise_for_status(self):
                pass

        return FakeResp()

    requests.get = fake_get
    try:
        data_layer._fetch_savant_csv("https://baseballsavant.mlb.com/leaderboard/statcast?csv=true")
        raise AssertionError("expected a RuntimeError for garbled binary content")
    except RuntimeError as e:
        msg = str(e)
        assert "brotli" in msg.lower(), "should name Brotli as the likely cause"
        assert "'br'" in msg, "should show the actual Content-Encoding value received"
    print("Garbled-binary response: raises a specific diagnostic naming the likely Brotli-decompression cause")


def test_normal_responses_not_falsely_flagged_as_garbled():
    """Both a good CSV and the original plain-HTML failure mode should be
    unaffected by the new garbled-binary detection — no false positives,
    and the HTML case keeps its original (correct) generic message rather
    than incorrectly suggesting a compression issue."""
    def fake_get_good(url, headers=None, timeout=None):
        class FakeResp:
            text = "player_id,player_name,avg_hit_speed\n123,Test Player,91.5\n"
            status_code = 200
            headers = {"Content-Type": "text/csv; charset=utf-8"}

            def raise_for_status(self):
                pass

        return FakeResp()

    requests.get = fake_get_good
    result = data_layer._fetch_savant_csv("https://baseballsavant.mlb.com/leaderboard/statcast?csv=true")
    assert len(result) == 1

    def fake_get_html(url, headers=None, timeout=None):
        class FakeResp:
            text = ('<!DOCTYPE html>\n<html lang="en_US">\n<head>\n'
                    "<title>Statcast Custom Leaderboards</title>")
            status_code = 200
            headers = {"Content-Type": "text/html; charset=utf-8"}

            def raise_for_status(self):
                pass

        return FakeResp()

    requests.get = fake_get_html
    try:
        data_layer._fetch_savant_csv("https://baseballsavant.mlb.com/leaderboard/statcast?csv=true")
        raise AssertionError("expected a RuntimeError for the HTML case")
    except RuntimeError as e:
        msg = str(e)
        assert "brotli" not in msg.lower(), "plain HTML should not get the brotli-specific hint"
        assert "blocking automated requests" in msg
    print("Good CSV and plain-HTML cases: unaffected by the new detection, no false positives")


if __name__ == "__main__":
    test_savant_csv_fetch_makes_exactly_one_request()
    test_savant_csv_fetch_still_html_raises_clear_error()
    test_get_savant_percentile_pool_uses_correct_url()
    test_column_mapping_classic_names()
    test_column_mapping_alternate_names()
    test_column_mapping_both_variants_present_no_crash()
    test_wrong_columns_raises_diagnostic_error()
    test_percentile_table_end_to_end()
    test_no_brotli_in_accept_encoding()
    test_garbled_binary_response_gets_specific_diagnostic()
    test_normal_responses_not_falsely_flagged_as_garbled()
    print("\nALL SAVANT LEADERBOARD REGRESSION TESTS PASSED")
