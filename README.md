# Batter Dashboard

An interactive Streamlit dashboard built on top of your `api_scraper.py` for
searching any batter in MLB or the full-season affiliated minors (AAA, AA, High-A, A), with pitch-type-filterable spray/zone charts and
percentile ranks against qualified hitters.

## Setup

```bash
pip install -r requirements.txt
streamlit run app.py
```

This opens in your browser at `http://localhost:8501`. It needs a normal
internet connection to reach `statsapi.mlb.com` (and `baseballsavant.mlb.com`
for MLB Statcast percentiles) — it will not work inside a locked-down sandbox.

## How to use it

1. **Sidebar**: pick a season and which levels to search, then pick a player
   from the dropdown (type to filter) and click **Load batter**.
2. First load for a player pulls every game they've played that season from
   the live MLB feed — this can take anywhere from a few seconds to a couple
   of minutes for a player with a full season of games. After that it's
   cached to disk in `cache/` and reloads instantly. Use the "Force refresh"
   checkbox to re-pull (e.g. after they've played new games).
3. The period selector right below the header (Full Season / Last N Games /
   Custom Range) scopes the stat tiles, percentiles, and everything below
   it. The filter row further down (pitch types, pitcher hand, home/away)
   only affects the tab charts (Spray/Zone, Pitch Mix, Plate Discipline,
   Batted Ball, Raw Data) — the headline tiles above it reflect the period
   selector only, not these filters. The Trends tab's own stat picker rolls
   over the selected period too, but ignores this filter row specifically,
   since a rolling trend restricted to one pitch type would have too few
   points per window to be useful.

## What's in it

**Time period selector** (all three pages, right below the header — Team
Dashboard's also governs the Pitch-Level Deep Dive section rather than
that section having its own separate control): Full Season / Last N
Games (or Last N **Starts** on the Pitcher Dashboard — see below) /
Custom Range. Scopes the stat tiles, percentile values, and every tab
below it to just that window.

The headline tiles on the Batter and Team Dashboards are computed
directly from the already-loaded pitch-level/bulk data for whatever
period is selected. The Pitcher Dashboard's ERA/WHIP/W-L/IP tiles and the
Team Dashboard's runs-per-game/hitting/pitching tiles work differently —
those come from official aggregate endpoints, not pitch-level data, so a
period-scoped view re-fetches a genuinely date-scoped version of that
same official source (`stats=byDateRange` instead of `stats=season`)
rather than trying to derive anything from play-by-play. This matters
most for pitching: ERA specifically depends on earned-vs-unearned-run
judgment calls that aren't reliably recoverable from the raw feed, so
that tile always comes from MLB's own scoring, full season or not.

One remaining exception: the Batter/Pitcher Statcast rows (Hard-Hit%,
Exit Velo, Chase%, Whiff%, Sweet-Spot%) always compare against the
full-season Baseball Savant pool — there's no verified way to date-scope
that specific leaderboard, so rather than guess, those rows just don't
change with the period selector, and the "Compare against" toggle
described below notes this explicitly whenever it's relevant.

**Pitcher Dashboard: "Last N Starts", genuinely starts-only.** Rather
than just relabeling "games" as "starts", whether a game counts as a
start is determined from the data itself — if the pitcher's earliest
recorded inning in that game is the 1st, it's a start; otherwise it's
relief. This matters for anyone who's both started and relieved in the
same season, where "last N games" and "last N starts" are genuinely
different sets of games — a swingman with 5 starts and 10 relief outings
selecting "Last 3 Starts" gets exactly those 3 starts, with the relief
outings in between correctly excluded.

### Update: "Last N Games" was pulling from games that hadn't been
### played yet

A user reported that the Team Dashboard's "Last N Games" broke — for a
team about 100 games into a 162-game season, selecting "Last 10 Games"
was computing from games 153-162 of the season, which obviously hadn't
happened. Root cause: `get_schedule_lookup` (used to translate "Last N
Games" into an actual date range) was returning the *entire scheduled
calendar* for the season — MLB publishes the full 162-game schedule in
advance, and the raw endpoint doesn't filter that down to "games played
so far" on its own. This wasn't unique to the Team Dashboard's period
selector either — it also fed `get_max_team_games`, which sets the
pitcher qualified-IP threshold, so that was quietly inflated to a
full-season assumption mid-season too (fewer pitchers than should
qualify would clear the bar until very late in the year).

Fixed at the source rather than patched per call site: `get_schedule_lookup`
now filters to games where `game_date` is strictly before today, so
every consumer of it — the Team Dashboard's period selector, the
pitcher qualified-IP threshold, the Pitch-Level Deep Dive's game list —
automatically only sees games that have actually been played. Verified
directly: built a synthetic 162-game schedule (100 past, 62 future) and
confirmed both `get_schedule_lookup` and `get_max_team_games` correctly
return 100, and that the Team Dashboard's "Last N Games" input bound and
resulting date range now only ever reach into the past. `CACHE_VERSION`
bumped, and the schedule cache now has a normal 6-hour refresh window
instead of caching forever — it hadn't had one before, which would have
meant a game played today wouldn't show up as "played" until a cache
was manually force-refreshed.

**Percentile comparison mode** (Batter Dashboard only): once you've picked
something other than "Full Season" above, a "Compare against" toggle
appears next to Percentile Rankings — **Full-Season League** (the
default: your period's stats vs. every qualified hitter's *full season*)
or **Same-Period League** (your period's stats vs. what other qualified
hitters did over that *same* date range, fetched fresh with real
`startDate`/`endDate` params, not just relabeled). This distinction
matters: a hot 5-game stretch compared against full-season league norms
will look more extreme than the same stretch compared against how the
rest of the league did over those same 5 games. The Statcast-derived rows
(Hard-Hit%, Exit Velo, Chase%, Whiff%, Sweet-Spot%) stay full-season in
both modes — there's no verified way to date-scope Baseball Savant's
leaderboard, so rather than guess, those rows just don't change, and a
caption says so when it's relevant.

This toggle still isn't on the Pitcher Dashboard, though the original
reason for that has partly changed. When this was written, the pitcher
page's headline percentile metrics (ERA/WHIP/K%/BB%/HR9/FIP) always used
the season-long official value regardless of the period selector, so a
period-scoped comparison pool would have compared his full season
against everyone else's shorter window — a real mismatch. That's no
longer quite true: the pitcher page's official stats are now genuinely
period-scoped too (see "Last N Starts" above), which removes the
original blocker. Adding the same toggle there is a reasonable follow-up
this build didn't build proactively, since it wasn't asked for directly —
the Statcast-derived rows (Whiff%/Chase%/Hard-Hit%/etc) would still need
to stay full-season-only either way, for the same Savant date-scoping
limitation as the batter page.

### Update: the toggle didn't actually change anything — found and fixed

A user reported that switching to "Same-Period League" left the
percentile bars unchanged. The bulk stats endpoint has a `stats=` type
parameter, and the original implementation kept `stats=season` (a fixed
"give me full-season totals" mode) and just appended `startDate`/
`endDate` on top of it — which, going by that report, the endpoint
appears to silently ignore. `stats=byDateRange` is the type actually
meant for a date-scoped query, and that's what a period-scoped fetch
uses now. `CACHE_VERSION` was bumped so a previously-cached, silently-
identical-to-season-long pool doesn't keep masking this.

This is still not independently verified from this build environment —
it's a more targeted second attempt based on the specific symptom
reported, not a confirmed fix. To make that checkable without another
round of guessing, the debug expander now shows the season-long pool's
mean AVG side by side with the period-scoped pool's mean AVG whenever
"Same-Period League" is active — if they're identical, the toggle still
isn't doing anything and that's visible immediately rather than only
showing up as unchanged percentile bars.

### Trends tab: pick your own stats

The Batter Dashboard's Trends tab now has a stat picker (up to 3 at
once, enforced by Streamlit itself) instead of a fixed AVG/K%/BB% chart
— AVG, OBP, SLG, OPS, ISO, BABIP, K%, BB%, Swing%, Zone%, Z-Swing%,
Chase%, Contact%, CSW%, Whiff% (overall, in-zone, and out-of-zone
specifically), Hard-Hit%, Sweet-Spot%, and Avg Exit Velo. Every stat
rolls over the same "last N plate appearances" window
(`compute_multi_rolling_trend` in `stats.py`) regardless of whether it's
naturally a per-PA outcome, a per-pitch swing-decision rate, or a
per-batted-ball quality rate, so up to 3 very different kinds of stats
stay on one comparable x-axis. Avg Exit Velo gets its own axis on the
right (it's an mph value, not a fraction); everything else shares the
left axis. Verified by cross-checking every stat's value, on a small
hand-built dataset, against the already-tested `compute_slash_line`/
`compute_plate_discipline`/`compute_statcast_summary` functions — see
the `compute_multi_rolling_trend` cross-check in `test_smoke.py`.

**Batter Dashboard** (`views/batter_dashboard.py`, the page you land on):
- Slash line + ISO/BABIP, Statcast summary (Hard-Hit%, Avg/Max Exit Velo,
  Sweet-Spot%), plate discipline (Zone%, Chase%, Whiff%, Contact%, CSW%,
  1st-pitch-strike%)
- A compact counting-stats row (PA, AB, H, 2B, 3B, HR, RBI, BB, SO, HBP)
  underneath the rate-stat tiles
- **Percentile rankings** vs qualified hitters at the player's level, shown
  as a Savant-style bar chart
- **Spray chart**, filterable by pitch type / pitcher hand / home-away, colored
  by outcome
- **Pitch location (zone) chart**, filterable the same way, with a glow on
  hard-hit pitches
- Pitch usage mix + a batting-stats-by-pitch-type table
- Swing-rate heatmaps by zone and by ball-strike count
- Exit velocity vs. launch angle scatter with a sweet-spot band
- Batted-ball profile (GB/FB/LD/PU%, Pull/Center/Oppo%)
- Rolling-window trend chart (AVG/K%/BB%) across the season
- Splits table (vs LHP/RHP, home/away)
- Raw filtered data table + CSV export

**Pitcher Dashboard** (`pages/1_Pitcher_Dashboard.py` — shows up automatically
in the left sidebar nav once you run the app):
- Official season line (ERA, WHIP, W-L, SV/HLD, IP, K/BB%, K/9, BB/9, HR/9,
  an approximate FIP) pulled directly from MLB's official per-player stats
  endpoint, not derived from play-by-play
- **Percentile rankings** with an adaptive comparison pool: starters get
  compared against the officially "qualified" pool (1 IP/team game, same
  rule as the ERA title); a pitcher below that IP threshold — i.e. almost
  any reliever — automatically gets compared against a lower relief-eligible
  floor instead, so bullpen arms still get a meaningful percentile rather
  than nothing
- **Pitch mix** + usage/whiff/velocity/spin/movement by pitch type, and pitch
  mix broken out by count situation (ahead/even/behind)
- **Velocity distribution** (box plot) and the classic **movement plot**
  (induced vertical break vs. horizontal break) by pitch type
- **Release point** consistency chart by pitch type
- Pitch location (zone) chart, reused from the batter side
- Plate discipline — framed correctly for a pitcher (Whiff%/Chase% induced
  are GOOD here, opposite of a hitter's own version of the same stat)
- Contact quality allowed: exit velo vs. launch angle, Hard-Hit%/Sweet-Spot%
  allowed, batted-ball type allowed
- Rolling trend (AVG-against, K%, BB%) — no rolling ERA, since earned vs.
  unearned runs isn't a call this data can make reliably
- Splits vs LHH/RHH and home/away
- Raw filtered data table + CSV export

**Team Dashboard** (`pages/2_Team_Dashboard.py`):
- Built entirely from bulk, league-wide endpoints (one request covers every
  team at a level), so it loads fast regardless of roster size — no
  per-player pitch pulls
- Team hitting line (Runs/Game, AVG/OBP/SLG/OPS, HR, K%/BB%) and team
  pitching line (ERA, WHIP, W-L, Saves, Runs Allowed/Game, K%/BB%)
- **Percentile rankings vs every other team** at that level, same
  Savant-style bar chart as the player pages
- **Statcast rollup** (MLB only): the team's own qualified hitters'/pitchers'
  average Hard-Hit%, Exit Velo, Chase%, Whiff%, Sweet-Spot% — built by
  reusing the same Savant pool already fetched for player percentiles, no
  new endpoint needed
- **Roster leaderboards**: hitters with at least a configurable minimum
  at-bats (30 by default, adjustable in the UI — keeps out September-callup
  and pitcher-batting noise without imposing a full "qualified" bar), and
  every pitcher who's appeared with no innings minimum at all, pulled from
  the same player-level leaderboards used for percentiles elsewhere in the
  app
- **Pitch-Level Deep Dive** (opt-in, separate load button): pulls the
  team's entire season of games at once — both sides of the ball, since a
  team bats and pitches in every game it plays — and unlocks:
  - Team hitting results **by pitch type seen**, and team pitching results
    **allowed by pitch type thrown** (reuses the same pitch-type-table logic
    as the player pages)
  - Team-wide plate discipline (swing-rate-by-zone heatmaps, Chase%/Whiff%,
    both produced and induced)
  - Contact quality produced vs. allowed (exit velo/launch angle, batted-ball
    profile — Pull/Center/Opposite now classifies each hitter by their own
    handedness, so mixed lineups aren't misclassified)
  - **Runs scored vs. runs allowed, rolling** — the most direct "is this
    team hot or cold" signal available
  - Team-wide rolling AVG/K%/BB% trends, both sides
  
  This is a genuinely heavy pull (up to 150+ full game feeds for a full
  season), so it's deliberately kept separate from the fast bulk-stat load
  above and cached afterward like everything else.

Deliberately left out of the Team Dashboard's bulk-stat section: pitch spray
charts and anything else that's only meaningful for one player at a time.
The Pitch-Level Deep Dive section above does include pitch-type/discipline/
contact charts at team scope, since those aggregate coherently across a
roster in a way a spatial spray chart or an individual movement plot don't.

## Where the percentile numbers come from

- **AVG/OBP/SLG/OPS/K%/BB% (batters), ERA/WHIP/K%/BB%/K-BB%/HR9/FIP (pitchers)**:
  pulled in bulk from the MLB Stats API season leaderboard for the player's
  level. Batters are restricted to `PA >= 3.1 x max games played`; pitchers
  to `IP >= 1.0 x max games played` (the same math MLB uses to define
  "qualified" at season's end). Works at every level, MLB and minors.
- **Hard-Hit%, Avg Exit Velo, Chase%, Whiff%, Sweet-Spot% (batters and their
  pitcher-side equivalents)**: pulled in bulk from Baseball Savant's public
  custom-leaderboard export, MLB only — Savant doesn't publish minor-league
  leaderboards, so these percentile bars simply don't appear for
  minor-league players (their own raw values still show up in the stat
  tiles).
- **Pitcher percentile pool is adaptive**: a starter gets compared against
  the officially qualified pool; anyone below that IP threshold (almost
  every reliever) gets compared against a much lower relief-eligible floor
  instead, so bullpen arms get a real percentile rather than nothing. The
  Pitcher Dashboard's caption under the percentile chart tells you which
  pool was used.

## A caching bug worth knowing about (fixed, but good to understand)

Early on, a real bug (Baseball Savant's percent-scale metrics needing to be
divided by 100) got fixed in the code, but kept showing up broken anyway —
because the *old, wrong* data was already cached to disk from before the fix,
and the cache's 6-hour freshness window meant it just kept serving the stale
file instead of re-fetching. Every leaderboard cache filename now embeds a
`CACHE_VERSION` (in `data_layer.py`) specifically so this can't happen again:
bumping that constant whenever the processing logic changes forces a fresh
pull instead of relying on someone noticing and manually clearing `cache/`.
If a stat ever looks stuck at an old wrong value after a code update, that
version bump is the first place to check.

## A pagination bug worth knowing about (also fixed)

The Team Dashboard's roster tables were only showing 4-5 players per team
even after adding the at-bats filter — turned out the MLB Stats API's bulk
player-leaderboard endpoint silently caps how many rows it returns per
request, regardless of the `limit` value asked for (a `limit=3000` request
was coming back with something far smaller). `_fetch_stats_splits()` in
`data_layer.py` now pages through with `offset` until a short page confirms
there's nothing left, rather than trusting one big request to return
everyone. `CACHE_VERSION` was bumped again alongside this fix so any
previously-cached truncated roster gets replaced automatically. If a roster
table ever looks suspiciously short again, the debug expander at the bottom
of the Team Dashboard now shows the total row count of the full (unfiltered)
league leaderboard plus a sample of team names present, so you can tell
right away whether it's a pagination gap or a name-matching mismatch.

## A missing-plate-appearance bug worth knowing about (also fixed)

A user reported Lazaro Montes' AAA slash line coming in lower than official
sources (.270/.361/.562 here vs. .274/.369/.571 officially) despite both
agreeing on games played — the kind of mismatch that means individual plate
appearances are silently vanishing from otherwise-correctly-pulled games,
not that whole games are missing.

Root cause, found in `api_scraper.py`'s `get_data_df`: an at-bat's outcome
(hit/out/walk/whatever) is only ever attached to the row for the
chronologically *last* recorded `playEvent` in that at-bat. The row-inclusion
check required that event to itself be a pitch — but MLB's live feed
sometimes logs a non-pitch event (a baserunning or defensive note) *after*
the batter's actual decisive pitch as the technically-last element in that
at-bat's event list. When that happened, the real outcome-bearing row got
silently excluded, and that whole plate appearance disappeared from AVG/OBP/
SLG — while the game itself, and its other at-bats, still counted normally.
That's exactly the symptom reported: games-played matches, slash line comes
in low.

Fixed by always including an at-bat's final event regardless of whether it's
itself a pitch (verified both directions — reverted the fix and confirmed
the dropped-PA behavior reproduces exactly, then confirmed the fix recovers
it; see `test_scraper_fix.py`). Since pitch logs are cached indefinitely
(not on a time-based TTL like the leaderboards), a new `PITCH_LOG_CACHE_VERSION`
in `data_layer.py` was added specifically so this fix — and any future one
like it — actually reaches previously-loaded players instead of silently
continuing to serve the old, wrong cached rows forever.

I can't fully confirm this closes 100% of the gap for Lazaro Montes
specifically without live access to verify his actual box scores, but the
mechanism reproduces the exact symptom reported (games match, rate stats
low) and the fix is verified correct in both directions.

**If you're still seeing the same numbers after this fix**, that most likely
means either (a) the Streamlit server process wasn't fully restarted after
updating the files — Python doesn't hot-reload changed modules, so the old
`api_scraper.py` logic stays in memory until you stop and re-run
`streamlit run app.py`, not just refresh the browser tab — or (b) there's a
second, different cause still dropping plate appearances for this specific
player. To tell which: reload the player with "Force refresh this player's
data" checked, then open the **Data source status** expander. It now runs a
diagnostic (`compute_orphaned_at_bats`) that counts at-bats with pitch rows
but no recorded outcome — this should read 0 if the fix is active and
sufficient. A prominent warning also appears right under the header if this
count is nonzero, so it's not something you'd need to go looking for.

### Update: the orphaned-at-bat count came back 0, but the numbers were
### still wrong — so there's a second issue

A 0 count there only proves individual plate appearances aren't getting
dropped *within a game that was successfully pulled*. It says nothing about
whether every game the player actually played got pulled in the first
place — if `get_player_games_list` misses a whole game, there's nothing
inside that missing game for the orphan check to find.

Two things followed from that:

1. **Much more direct diagnostics.** The page now shows "Pulled N games ·
   M plate appearances · date range" right under the header (compare N
   directly against an official source's games-played number), and the
   debug expander has a full breakdown of every `event_type` string that
   showed up in the pulled data. If a discrepancy shows up again, these
   numbers make it possible to say precisely where — missing games vs.
   miscounted events — instead of guessing from the final slash line alone.
2. **A second plausible fix, applied but unverified.** `api_scraper.py`
   was building request URLs with a non-standard `gameType=[R]` (literal
   brackets) instead of `gameType=R` in both `get_player_games_list` and
   `get_players`. This is genuinely non-standard query-string syntax, and
   fixing it is low-risk — but I want to be direct that I can't confirm
   from here whether this was actually causing games to go missing;
   removing it could turn out to have zero effect on this specific case.
   `PITCH_LOG_CACHE_VERSION` was bumped again so this reaches anyone who
   already pulled data under the previous fix.

If the games count still comes in short of the official number after a
real restart + force refresh, that's the concrete next data point — share
it and I can work from that instead of a guess.

### Update: found it — the counts were running HIGH, not low, and that's
### a different bug entirely

With real numbers to work from (205 PA / 178 AB / 24 BB here vs. Baseball
Reference's 203 PA / 175 AB / 25 BB), the arithmetic pointed somewhere new:
PA is roughly AB + BB, and the deltas here (+3 AB, −1 BB) net to exactly +2
PA — matching the PA delta precisely. That's the opposite signature from
the dropped-plate-appearance bug above: *extra* plate appearances, not
missing ones, meaning something was being double-counted.

Root cause: MLB's per-player game log can list the same `gamePk` more than
once — a suspended-and-resumed game is the classic case — so
`get_player_games_list` returned a duplicate game ID, that game got pulled
and processed twice, and every plate appearance in it got counted twice.

Fixed in `data_layer.py` two ways:
1. `_dedupe_game_ids()` removes duplicate IDs from the game list *before*
   pulling — prevents the double-fetch outright, and saves a wasted
   network call in the process.
2. `_dedupe_pitch_rows()` is a safety net applied to the resulting
   dataframe regardless: drops any exact duplicate
   `(game_id, ab_number, index_play)` rows, since that triple should
   uniquely identify one pitch/play event — a repeat can only be a data
   artifact, never a legitimate second row, whatever the source.

Verified end-to-end with a test that fakes a duplicated game ID in the
game list and confirms the pipeline produces exactly the right plate-
appearance count rather than an inflated one (`test_scraper_fix.py`). A
new diagnostic, `compute_duplicate_at_bats`, is the mirror image of the
orphaned-at-bat check from before — it flags any at-bat with *more* than
one recorded outcome, shown as a prominent warning under the header plus
detail in the debug expander. `PITCH_LOG_CACHE_VERSION` was bumped again
so this reaches data already pulled under the previous fixes.

### Update: still running high after the dedup fix — the actual remaining
### cause, found from the user's own hypothesis

The user's guess was close to exactly right: "could a runner being thrown
out create an extra at-bat?" MLB's game feed records two different kinds
of entries in a game's play list — genuine at-bats (`result.type ==
'atBat'`) and standalone non-PA "action" plays like caught stealing,
pickoffs, stolen bases, and mound visits (`result.type == 'action'`),
which get their own entry in the list and can still reference a batter
even though they aren't a plate appearance.

The very first fix in this thread (recovering at-bats whose final event
wasn't itself a pitch) was scoped too broadly: it applied to *every*
entry in the play list, not just genuine at-bats. So a caught-stealing
play's trailing event — carrying `eventType: "caught_stealing_2b"` or
similar, not a real batting outcome — could get swept up and counted as
though the batter had come to the plate again, inflating PA and AB
without a matching hit. This was the actual mechanism behind counts
still running high after the game-ID dedup fix.

Fixed by skipping any `allPlays` entry that isn't `type == 'atBat'`
before processing it at all, in `api_scraper.py`'s outer play loop —
which keeps the original dropped-plate-appearance fix correctly scoped
to real at-bats only. Verified both directions again: confirmed the
pre-fix code genuinely produced a `caught_stealing_2b` "plate appearance"
from a synthetic caught-stealing play, then confirmed the fix removes it
while leaving every genuine at-bat (including the one from the original
fix's own edge case) intact. Permanent regression test added alongside
the other two in `test_scraper_fix.py`. `PITCH_LOG_CACHE_VERSION` bumped
again.

### Raw data export, for when a discrepancy needs a closer look

Both the Batter and Pitcher Dashboards now have a **"Download full raw
pitch log (CSV)"** button at the top of the "Data source status" debug
expander — the entire season's pitch/plate-appearance data for that
player, unfiltered, exactly what every stat on the page is computed from.
If something still looks wrong after checking the diagnostics above,
downloading this and attaching it to a chat message is the fastest way
to get it debugged directly against real data rather than guessing from
summary numbers alone.

### Update: fixed for real, verified against the user's actual exported
### data — this one isn't a guess

The `type == 'atBat'` fix above wasn't the whole story. The user exported
their real raw pitch log via the button above and attached it, which
turned this from "reasoning about a hypothesis" into "reading the actual
numbers" — and it showed `caught_stealing_2b` still present, twice, even
after that fix. Looking at those two rows directly: they had real pitch
data attached (an actual 89-92 mph fastball, mid-count) and were
genuinely typed `atBat` — this is what happens when a baserunner gets
thrown out for the third out *while the batter's own count is still in
progress*. MLB still files it under that at-bat's entry with
`eventType: "caught_stealing_2b"`, so the `type == 'atBat'` check alone
couldn't distinguish it from a real plate-appearance result.

The same export also surfaced a second, unrelated bug: `intent_walk`
was never being recognized as a walk anywhere in `stats.py` (only the
exact string `"walk"` was checked), so it fell through and got counted
as an at-bat — 0-for-1 — instead of being excluded from AB and added to
BB like a normal walk.

Both are now fixed directly in `stats.py`:
- `is_non_pa_event()` excludes baserunning/administrative outcomes
  (`caught_stealing_*`, `pickoff_*`, `stolen_base_*`, `wild_pitch`,
  `passed_ball`, `balk`, and a few others) from PA and AB counting
  everywhere a plate-appearance dataframe gets built — `compute_slash_line`,
  `compute_pitch_type_table`, `compute_rolling_trend`, and the pitcher-side
  equivalent in `stats_pitching.py`. These rows are deliberately *not*
  scrubbed from the raw data itself, so `compute_data_completeness_summary`
  still shows them in the full event breakdown for transparency — it now
  reports both the corrected PA count and, separately, exactly what got
  excluded and why.
- `WALK_EVENTS = ["walk", "intent_walk"]` replaces every exact `== "walk"`
  check, and `intent_walk` was added to `NON_AB_EVENTS`.

Verified directly against the real exported CSV (not just a synthetic
reproduction): `compute_slash_line` on that actual data now produces
203 PA / 175 AB / 25 BB and a .274/.369/.571 slash line — an exact match
to Baseball Reference, down to the digit. Confirmed again end-to-end
through the full rendered dashboard page using that same file, with zero
exceptions and zero diagnostic warnings. A fourth regression test,
built directly from this exact bug pattern, is now permanent in
`test_scraper_fix.py`.

## Mobile

Streamlit's `st.columns()` doesn't reflow on its own — a 6-tile stat row
or two side-by-side charts just get squeezed into whatever width is
available, which on a phone screen makes both unreadable rather than
just smaller. `theme.py` adds a `@media (max-width: 640px)` rule that
forces most column rows across all three pages to stack into a single
column below that width. Plotly charts (rendered with `width='stretch'`)
automatically fill whatever width their container ends up with, so they
benefit from this without any chart-specific changes.

The exact CSS selectors this depends on (`stHorizontalBlock`/`stColumn`)
were confirmed directly against this project's installed Streamlit
version's own compiled frontend bundle, not assumed from general
Streamlit knowledge — a wrong selector here would make the whole fix a
silent no-op, so this was checked rather than guessed.

### Update: real phone feedback, four more fixes

After trying it on an actual phone: the top bar covered the player
name, the stat tiles took too much scrolling, the pitch-type checkboxes
were fiddly to tap, and some charts looked "zoomed way out." All four
fixed:

- **Header covering content.** The earlier mobile CSS had reduced
  `.block-container`'s `padding-top` to reclaim vertical space — but
  that padding is what Streamlit relies on internally to clear its own
  fixed header bar, so shrinking it let the header sit on top of the
  page title instead of above it. Fixed by only touching the *side*
  margins, which have no such dependency, and leaving Streamlit's own
  top padding alone. `test_mobile_css.py` now specifically asserts this
  override can't come back.
- **Stat tiles took too much scrolling.** Added a rule using the CSS
  `:has()` selector that detects metric-tile rows specifically (as
  opposed to chart rows) and wraps them into roughly 3-per-row instead
  of fully stacking to one-per-row — 12 tiles now take about 4 rows of
  scrolling instead of 12. `:has()` needs a reasonably modern browser
  (Chrome/Edge 105+, Safari 15.4+, Firefox 121+) — effectively any phone
  browser that's auto-updated recently.
- **Pitch-type checkboxes.** Replaced with `st.pills` in
  `selection_mode="multi"` — Streamlit's native toggle-chip widget,
  exactly the "tap the word itself, it lights up when active" pattern
  asked for. Verified end-to-end: default state selects every pitch
  type, narrowing the selection correctly narrows what feeds the tab
  charts, no exceptions.
- **Charts "zoomed way out."** Traced to three charts (`spray_chart`,
  `zone_chart`, `discipline_heatmap`) that lock their aspect ratio to
  real-world units via Plotly's `scaleanchor`/`scaleratio` (so a strike
  zone or field diagram doesn't look stretched). At the old fixed
  heights (460-520px) on a narrow phone width, Plotly has to shrink the
  actual plot down small to preserve that ratio within a much-taller-
  than-wide container, leaving a lot of empty space around it — which
  reads exactly as "zoomed out." Reduced and aligned all of them (plus
  `count_heatmap`, which pairs with `discipline_heatmap` side-by-side on
  desktop) to a consistent height of 420px, closing most of that gap
  while keeping their desktop pairings visually matched.

What wasn't possible from this build environment: an actual screenshot
on a real phone or a real browser at phone width — a Chrome browser
tool was attempted and is available in principle, but the extension
wasn't connected in this session. What's verified instead: the CSS
renders without exceptions, targets the confirmed-correct selectors,
doesn't reintroduce the header-covering padding bug, and has balanced
syntax (`test_mobile_css.py`); the pills widget is exercised end-to-end
through the actual rendered UI; and the chart height math is worked out
from each chart's actual data range, not guessed. If anything still
looks off on your actual phone, that's the next thing to check.

### Update: real feedback from the deployed site, six more fixes

After actually using the deployed version on a phone: the sidebar
levels weren't touch-friendly, three of the five levels turned out to
have no usable stats, the player search box kept auto-filling a name
that had to be deleted every time, the page nav wasn't easy to spot,
the sidebar buried the player picker below other controls, the Batted
Ball tab's chart was squeezed to one side, and "Percentile Rankings"
showed up twice. All fixed:

- **Levels reduced to MLB and AAA only.** AA/High-A/A were removed from
  `data_layer.LEVELS` entirely, based on the report that they returned
  no usable stats against the live deployment — trusted as real signal
  from an actual run against `statsapi.mlb.com`, which this build
  environment can't reach itself. `CACHE_VERSION` bumped so a
  previously-cached roster including those levels doesn't linger.
- **Levels and Team-page Level selector are now `st.pills`** (multi-
  select on Batter/Pitcher, single-select-required on Team) instead of
  checkboxes/a dropdown — the same tap-to-toggle pattern already used
  for pitch types.
- **No more autofilled player/team name.** Every search box (Batter,
  Pitcher, Team) now starts empty (`index=None` + placeholder text)
  instead of defaulting to the first option in the list. Verified
  directly: the widget's value is `None` on load and the Load button
  stays disabled until something is actually picked.
- **Sidebar reordered.** "Refresh player list" and "Force refresh" moved
  into a collapsed "Advanced" expander below the Load button, so the
  primary flow — Season → Levels → Player → Load — is short and the
  player picker isn't buried under maintenance controls.
- **Page nav made obvious.** The Batter/Pitcher/Team Dashboard sidebar
  links are now bigger, bolder, and clearly highlight whichever page is
  active, using `stSidebarNav`/`stSidebarNavLink`/`aria-current="page"`
  — confirmed as real strings in this Streamlit version's compiled
  frontend before relying on them, not guessed. Also trimmed the padding
  above the nav block, which was most of the reported "dead space."
- **Batted Ball tab squish — an actual bug in the mobile CSS from last
  round.** The `:has()` rule that wraps metric-tile rows checks for a
  metric *anywhere* in a row's descendants, not just direct children —
  so it also incorrectly matched the Batted Ball tab's chart-next-to-a-
  metrics-column layout (the metrics are nested one level deeper inside
  the second column, not siblings of the chart), squeezing the chart
  down to ~31% width instead of stacking it full-width. Fixed with a
  more specific rule that detects Plotly charts specifically and always
  wins that tie — verified both that the fix exists and that it's
  correctly ordered *after* the metric rule in the stylesheet, since
  that ordering is what makes the tie-break work (`test_mobile_css.py`).
- **Duplicate "Percentile Rankings"** — the chart itself carried its own
  Plotly title, on top of every page's own section header above it.
  Removed the chart's internal title (`charts.percentile_bars`), and
  taught the shared chart-layout helper to reclaim the wasted top
  margin when a chart has no title instead of leaving a blank gap. The
  Team Dashboard didn't have its own section header at all — it was
  relying entirely on the now-removed chart title — so it got one added
  for both the hitting and pitching percentile sections. Verified:
  exactly one "Percentile Rankings" heading renders per section, and
  `test_smoke.py` now asserts the chart never carries an internal title.

## Deploying it (so you can use it from your phone)

Running `streamlit run app.py` only starts a local web server — your
phone can't reach `localhost` on your computer over the internet, so
"deploying" means getting that server running somewhere your phone
*can* reach it. Two realistic paths:

**Same-WiFi, zero setup.** While the app is running on your computer,
add `--server.address 0.0.0.0` to the run command
(`streamlit run app.py --server.address 0.0.0.0`) so it accepts
connections from other devices, not just itself. Then, on your phone
(same WiFi network), visit `http://<your-computer's-local-IP>:8501` —
find that IP via your computer's network settings (something like
`192.168.1.x`). Free, but only works while your computer is on, the app
is running, and both devices are on the same network.

**Streamlit Community Cloud — a real URL, available anytime.** This is
the natural fit since it's built specifically for Streamlit apps, and
it's free:
1. Push this project to a GitHub repository (public or private both work).
2. Go to `share.streamlit.io` and sign in with your GitHub account.
3. Click **Create app** → **Yup, I have an app** → fill in the repo,
   branch, and file path (`app.py`).
4. Optionally pick a custom subdomain, then click **Deploy**.
5. Community Cloud reads `requirements.txt` automatically and installs
   everything — most apps are up within a few minutes. You get a public
   URL like `https://your-app-name.streamlit.app`, reachable from any
   browser, phone included.

A few things worth knowing before you do this:
- This app makes outbound calls to `statsapi.mlb.com` and
  `baseballsavant.mlb.com` at runtime — both are public, unauthenticated
  endpoints, so there's no API key or secret to configure in Community
  Cloud's "Secrets" panel for this specific app.
- The `cache/` folder speeds up repeat loads by caching to local disk.
  On a cloud deployment, that disk isn't guaranteed to persist across
  every redeploy the way it does running locally — not a functional
  problem (the app just re-fetches and rebuilds the cache as needed on
  a cold start), just don't expect the "instant reload" benefit to
  always carry over after you push a code update.
- By default, an app deployed to Community Cloud is publicly reachable
  by anyone with the URL. If you'd rather it not be, check Streamlit's
  current docs on restricting viewer access — that capability and its
  exact terms may have changed since this was written, so it's worth
  confirming directly rather than trusting a static claim here.

If you'd rather not touch GitHub, other general-purpose hosts (Render,
Railway, Fly.io, a small VPS) can run this too, but need more manual
setup — a start command or Dockerfile, not just point-and-deploy. Given
this is a personal tool with no auth requirements, Community Cloud is
the least amount of new work for the result you're after.

## Update: fixes from the actual live deployment

Two things reported directly against the deployed site (not something
this build environment could have caught on its own, since it has no
internet access to either of these endpoints):

**Baseball Savant's CSV export started returning the plain HTML
leaderboard page instead of CSV data**, breaking Statcast percentiles
(Hard-Hit%, Chase%, Whiff%, etc — the standard-stat percentiles like
AVG/OBP/SLG were unaffected, since those come from a different, MLB
Stats API endpoint that kept working). The request already had a
realistic User-Agent/Accept/Referer before this, so simple header
spoofing wasn't the fix. See the update below for how this played out —
the first attempted fix here made things worse, not better.

**Sidebar order.** All three pages now render Player/Team search first,
*then* Season, *then* Levels, then the Load button, with "Force
refresh"/"Refresh player list" tucked into the "Advanced" expander at
the very bottom — matching the requested order exactly (the page
navigation itself, i.e. Batter/Pitcher/Team Dashboard, is Streamlit's
native top-of-sidebar element and was already first).

The tricky part: the search box's own options depend on Season/Levels,
which now render *below* it. This works by reading each filter's
current value out of `st.session_state` before its own widget runs
later in the same script — Streamlit persists a widget's value across
reruns under its key, so this reflects whatever was last picked, and
correctly cascades to the search box above it the next time anything
changes. Verified two ways, not just that it renders without error:
the elements actually appear in the requested order, and changing a
filter (Levels) actually narrows the search box's options on the next
run (`test_sidebar_order.py`) — proving the cascade really works, not
just that the fallback defaults happen to render once without a crash.

### Update: the Savant fix made it worse, and the nav divider was too big

Two more rounds of direct feedback against the live site.

**Savant, continued.** The header-improvement fix above also added a
"warm-up" request — a GET to the plain leaderboard page first, to pick
up cookies, immediately followed by the real CSV request. A follow-up
report said the error was still happening and started after "a recent
change," which pointed straight at that warm-up step: firing two
requests back to back within milliseconds is exactly the kind of timing
pattern real bot-detection systems look for — no human loads a page and
clicks "export" that fast — so it plausibly made things *worse*, not
better. Reverted back to a single request, keeping the fuller header
set (pure additive realism, no behavioral downside) but dropping the
warm-up entirely. `test_savant_fetch.py` now specifically asserts
exactly one request gets made per call, so that warm-up step can't
silently creep back in without a test catching it.

Still being direct: this isn't confirmed to fix it either. The
IP-range-blocking possibility from the update above is still on the
table and still not something any request/header change can rule out
or fix from here. If it's still broken after this, the diagnostic in
the error message (Content-Type header + first 300 chars of the actual
response) is the real next data point — happy to keep working it with
that in hand rather than another guess.

**Sidebar nav spacing.** The accent-highlighted Batter/Pitcher/Team
Dashboard links had a visible divider line and a fairly large margin
below them, reported as taking up too much space for what it's doing.
Removed the line entirely and cut the margin down to a fourth of what
it was — still enough of a visual break from the search controls below
it, just not its own dedicated chunk of the sidebar.

### Update: found the actual Savant bug — wrong endpoint entirely

A follow-up report with the exact same error, after two rounds of
header/session changes that produced byte-for-byte identical responses,
was the real signal: this was never a header or bot-detection problem.
It was the URL itself.

`get_savant_percentile_pool` had always used `/leaderboard/custom` —
Baseball Savant's interactive leaderboard *builder* tool, the one you
click through in a browser to assemble custom columns. Its `csv=true`
parameter almost certainly never triggers a server-side CSV response at
all; that tool's export is more likely generated entirely client-side
by JavaScript from data already loaded on the page. No header, cookie,
or session change could ever have fixed a request to the wrong URL.

Found the actual correct endpoint by checking **pybaseball's real, public
source code** — a widely-used, actively-maintained Python library whose
own batted-ball leaderboard functions depend on a completely different,
verified-working URL: `/leaderboard/statcast?type=batter&year={year}
&position=&team=&min=q&csv=true`. Switched to that. Along the way, also
found independent confirmation — a separate actively-maintained
package's own "Known Issues" documentation — that Baseball Savant's
*plate-discipline* leaderboard (the one Chase%/Whiff% would come from)
has a real, currently-acknowledged outage on Savant's own end, returning
CSV headers with no data rows. That's not something any fix on this end
can work around.

So the fix lands in two parts:
- **Hard-Hit%, Avg Exit Velo, Sweet-Spot%** — now sourced from the
  verified `/leaderboard/statcast` endpoint. The exact column names it
  returns still aren't independently verified from this build
  environment, so `SAVANT_METRICS` hedges by mapping two plausible
  naming conventions (Savant's long-established classic names, and the
  newer names this app was previously guessing) to the same internal
  targets — whichever one is actually in use gets picked up without
  needing to know in advance which it is. If somehow neither matches,
  `_process_savant_csv` raises a clear error showing the actual column
  names received, so a next round has real data instead of another guess.
- **Chase%/Whiff%** — no longer expected from Savant at all, since
  there's no verified-working source for that specific league-wide
  comparison right now. Each player's *own* Chase%/Whiff% values still
  show correctly (those were always computed locally from pitch-level
  data, never from Savant) — they just won't have a league percentile to
  compare against for now. A caption under the percentile chart explains
  why, on MLB pages specifically, rather than leaving two silently blank
  bars that look like another bug.

Tested thoroughly against simulated responses rather than just asserted
correct: the URL construction for both batter and pitcher, both plausible
column-naming conventions independently, the duplicate-column edge case
that mapping two names to one target can create if a response somehow
contains both, the "still returns HTML" and "neither naming convention
matches" error paths, and the full percentile table end-to-end (real
percentiles for the three available metrics, graceful no-percentile
handling for the two that aren't) — all in `test_savant_fetch.py`.

### Update: garbled binary instead of HTML — a different bug, this app's own

A follow-up report after the endpoint fix above showed real progress —
**Content-Type now correctly said `text/csv`**, confirming Savant was
genuinely trying to send CSV data — but the response body itself was
garbled, mostly-unprintable binary rather than text.

Cause: one of the earlier "more realistic headers" rounds had added
`"br"` (Brotli) to the Accept-Encoding header, to look more like real
browser traffic. That backfired specifically — advertising Brotli
support tells a server it's free to compress the response that way, but
`requests` can only automatically decompress Brotli if the optional
`brotli`/`brotlicffi` package is installed, which it isn't in this
environment (checked directly: `import brotli` fails here, and almost
certainly fails the same way on a default Streamlit Community Cloud
environment, since it's not a common default dependency). Without that
package, the raw compressed bytes come through as if they were the
final content, and reading them as UTF-8 text produces exactly this
kind of garbage.

Fixed by dropping `"br"` from Accept-Encoding — back to `"gzip, deflate"`,
which is confirmed directly to be `requests`' own actual default when
this header isn't set manually at all, so this isn't a guess about what's
safe, it's what the library already does on its own. Also added a
specific check for this exact failure shape (a response that's mostly
unprintable characters) to the error message itself, so if anything
similar ever happens again — a different compression mismatch, or
anything else that produces garbled binary instead of text — the error
names the likely cause directly instead of the generic "blocking
automated requests" message, which doesn't point anywhere useful for
this particular kind of failure.

Verified directly rather than assumed: confirmed brotli isn't installed
in this environment, confirmed `requests`' own real default Accept-
Encoding value, and reproduced the exact garbled-binary shape from the
report to confirm the new diagnostic correctly identifies it — while
confirming a normal good CSV response and the original plain-HTML
failure mode are both unaffected (no false positives from the new
check) — all in `test_savant_fetch.py`.

## Known limitations / heads-up

- **This was built without live access to `statsapi.mlb.com` or
  `baseballsavant.mlb.com`** — the sandbox this was built in only allows
  outbound network access to package registries, not general internet. The
  endpoint shapes follow the same patterns already working in your
  `api_scraper.py`, plus Baseball Savant's well-documented CSV export, and
  everything was tested end-to-end against synthetic datasets built to match
  the real schema exactly (`test_smoke.py`/`test_happy_path.py` for the
  batter page, `test_pitching_smoke.py`/`test_pitcher_happy_path.py` for the
  pitcher page). But since it's never hit the live APIs, there's a real
  chance a field name has moved since these endpoints were last documented —
  this already happened once (see the caching section above). If a chart or
  stat comes up empty/wrong:
  - Open the **Data source status (debug info)** expander under the
    percentile chart on either page — it shows exactly how many rows/columns
    came back from each source.
  - Open the **Raw Data** tab and check the columns actually came through.
  - For leaderboard issues, the error messages from `data_layer.py` now
    include the actual columns Savant/MLB returned, so you shouldn't need to
    add debug prints — just read the warning banner.
  - **The pitcher-side Baseball Savant field names
    (`PITCHING_SAVANT_METRICS` in `data_layer.py`) and the team-level
    endpoint (`/api/v1/teams/stats`) are the least-verified parts of this
    build** — the batter-side Savant fields and player-level MLB Stats API
    endpoints were confirmed working against live data over the course of
    building this, but the pitcher Savant equivalents (`p_era`,
    `fastball_avg_speed`, etc.) and the team-stats endpoint are best guesses
    based on the same naming/shape conventions. If the Pitcher Dashboard's
    Savant-based percentiles, or the Team Dashboard's percentile charts or
    roster tables, come up empty, check the relevant debug expander first —
    the error message will show you the real column names to fix the
    mapping with.
- **Pull/Center/Oppo** direction is derived from the raw hit-coordinate sign
  convention, which also couldn't be verified live. If it looks mirrored for
  a hitter you know is pull-heavy, flip `PULL_SIGN_FLIP = True` at the top of
  `stats.py`.
- **Minor-league data quality varies a lot by level and year.** Full
  Statcast-quality pitch tracking (exit velo, spin rate, etc.) is inconsistent
  below AAA and even at AAA isn't in every park/season. Some
  players will show a complete slash line but sparse or missing Statcast
  numbers — that's the underlying MLB data, not a bug here.
- **A player who gets called up/sent down mid-season** shows up once per
  level in the search dropdown; each entry only pulls games at that level. If
  you want a combined "whole year across levels" view, that's not built in.
- **`get_players()`** in `api_scraper.py` doesn't filter by position, so
  pitchers show up in the search list too (harmless for a batter-focused
  tool, but worth knowing).

## Look and feel

Palette is **Deep Jewel Tones** — one of six documented dark-mode palettes
from [vev.design's dark mode color palette guide](https://www.vev.design/blog/dark-mode-website-color-palette/):
rich black background, off-white text, and three jewel accents split across
the pages (Batter=teal, Pitcher=ruby, Team=forest green). The base
background/text hex values are used as documented; the three accent jewel
tones are brightened from their published values since the originals are
calibrated for large surface areas, not a thin UI accent that needs to read
against a near-black background. `theme.ACCENTS` and `theme.LEVEL_COLORS`
at the top of `theme.py` are the only place you need to touch to change any
of this.

Metric tiles are plain typography — no box, no border, no colored side-bar
— just a bold number under a small muted label with a thin bottom rule
separating rows, the way a stat table reads rather than a card grid. The
percentile bar chart's color scale runs sapphire blue (below average)
through topaz gold (average) to true red (elite) — deliberately a real red
at the top end, not the pink/magenta a lot of "AI-generated-looking"
gradients default to.

Streamlit's default top bar (the "Deploy" button and hamburger settings
menu) is hidden via `toolbarMode = "minimal"` in `.streamlit/config.toml`
— this is a personal local tool, not something being pushed to Streamlit
Community Cloud, and that bar was otherwise just empty space across the
top of every page. The sidebar's own collapse/expand arrow is a separate
UI element and isn't affected by this setting.

Each player/pitcher page leads with their season stat line and percentile
ranks (unfiltered) immediately after the header — that's the headline
information, so it comes first. The pitch-type/hand/location filters live
further down, positioned right above the tabbed charts they actually affect,
since that's the only part of the page they change.

Level and pitch-type filters are checkboxes rather than multiselect
dropdowns. The rolling-PA-window slider only appears above the Trends tab
on the batter/pitcher pages, since that's the only place it's used.
Explanatory captions were stripped out in favor of letting chart titles and
axis labels speak for themselves — the one exception is the collapsed
"Data source status" debug expander on each page, kept because it's
genuinely useful for diagnosing a data issue and doesn't add visual clutter
since it's closed by default. Player headshots were removed.

## Files

```
app.py                          Navigation router only — sets page config, declares the 3 views with titles
views/batter_dashboard.py       Streamlit UI — Batter Dashboard
views/pitcher_dashboard.py      Streamlit UI — Pitcher Dashboard
views/team_dashboard.py         Streamlit UI — Team Dashboard
theme.py                        Shared styling (fonts, cards, headers) used by all three pages
period_ui.py                    Shared "Full Season / Last N Games / Custom Range" selector widget
data_layer.py                   Network calls + disk caching (rosters, pitch logs, leaderboards)
stats.py                        Pure batter stat computations (no network)
stats_pitching.py               Pure pitcher stat computations (no network)
stats_team.py                   Pure team stat computations (no network)
charts.py                       Plotly chart builders shared by all three pages
charts_pitching.py              Plotly chart builders specific to pitchers
api_scraper.py                  Your original scraper, untouched
test_smoke.py                   Unit-level test of stats.py/charts.py, incl. multi-stat trend cross-check
test_happy_path.py              Full end-to-end batter-page test with mocked data_layer functions
test_pitching_smoke.py          Unit-level test of stats_pitching.py/charts_pitching.py
test_pitcher_happy_path.py      Full end-to-end pitcher-page test with mocked data_layer functions
test_team_happy_path.py         Full end-to-end team-page test with mocked data_layer functions
test_scraper_fix.py             Regression tests for the four data-correctness bugs found and fixed
test_period_selector.py         End-to-end period-selector test (uses a real CSV export if present, else skips)
test_compare_mode.py            Regression tests for the compare-mode toggle and the schedule column-collision fixes
test_pitcher_starts.py          Regression tests for Last-N-Starts detection and period-scoped official pitching stats
test_team_period.py             Regression test proving Team Dashboard tiles (Runs/Game etc) respond to the period selector
test_mobile_css.py              Regression test for the mobile-responsive CSS (selectors, valid syntax)
test_savant_fetch.py            Regression test for the Savant CSV fetch (session/headers, error handling)
test_sidebar_order.py           Regression test for the sidebar element order and its session-state cascading
cache/                          Disk cache (rosters, pitch logs, leaderboards) — safe to delete anytime
```

Run the same way as always — `streamlit run app.py` — nothing changed there. Internally,
`app.py` used to *be* the batter dashboard; it's now a thin router using Streamlit's
`st.navigation`/`st.Page` API so each page gets a proper sidebar title ("Batter Dashboard",
"Pitcher Dashboard", "Team Dashboard") instead of the old bug where the entry page just
showed up as "app". The actual page content lives in `views/`.

