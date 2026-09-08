"""
charts.py
─────────
Every Plotly figure the dashboard renders. All charts share a common dark
palette so the app reads as one cohesive tool rather than a pile of default
Streamlit widgets.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from stats import PITCH_COLORS, SZ_LEFT, SZ_RIGHT, shorten_pitch

BG = "#151532"
PANEL = "#1b1b40"
GRID = "#34345f"
MUTED = "#adadd6"
ACCENT = "#2f9bb5"


def _base_layout(fig: go.Figure, title: str, height: int = 420) -> go.Figure:
    layout_kwargs = dict(
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(color=MUTED),
        height=height,
        margin=dict(l=40, r=20, t=(50 if title else 15), b=40),
        legend=dict(bgcolor=PANEL, bordercolor=GRID, borderwidth=1, font=dict(color="white")),
    )
    if title:
        layout_kwargs["title"] = dict(text=title, font=dict(color="white", size=16))
    fig.update_layout(**layout_kwargs)
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, color=MUTED)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, color=MUTED)
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Spray chart
# ─────────────────────────────────────────────────────────────────────────────

HIT_COLORS_MAP = {"single": "#FFFF00", "double": "#FFA500", "triple": "#00FFFF", "home_run": "#FF3030"}


def spray_chart(enriched_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()

    # Outfield wall
    theta = np.linspace(np.radians(45), np.radians(135), 200)
    r = 330 + 70 * np.sin(2 * (theta - np.pi / 4))
    wall_x, wall_y = r * np.cos(theta), r * np.sin(theta)
    fig.add_trace(go.Scatter(
        x=[0] + list(wall_x) + [0], y=[0] + list(wall_y) + [0],
        fill="toself", fillcolor="#173617", line=dict(color="#173617"),
        hoverinfo="skip", showlegend=False,
    ))
    fig.add_trace(go.Scatter(x=wall_x, y=wall_y, mode="lines",
                              line=dict(color="white", width=2), hoverinfo="skip", showlegend=False))

    # Foul lines
    foul_len = 340
    for sign in (1, -1):
        fig.add_trace(go.Scatter(
            x=[0, sign * foul_len * np.cos(np.radians(45))],
            y=[0, foul_len * np.sin(np.radians(45))],
            mode="lines", line=dict(color="white", width=1), opacity=0.6,
            hoverinfo="skip", showlegend=False,
        ))

    # Infield dirt diamond + mound
    diamond_x = [0, 63.64, 0, -63.64, 0]
    diamond_y = [0, 63.64, 127.28, 63.64, 0]
    fig.add_trace(go.Scatter(x=diamond_x, y=diamond_y, fill="toself",
                              fillcolor="rgba(107,74,30,0.4)", line=dict(color="white", width=1.5),
                              hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=[0], y=[60.5], mode="markers",
                              marker=dict(size=16, color="rgba(107,74,30,0.4)", line=dict(color="white", width=1)),
                              hoverinfo="skip", showlegend=False))

    bip = enriched_df[(enriched_df["in_play"] == True) & enriched_df["x_ft"].notna()].copy()  # noqa: E712
    if bip.empty:
        return _base_layout(fig, "Hit Spray Chart — no batted-ball location data for this filter", height=420)

    outs = bip[~bip["event_type"].isin(HIT_COLORS_MAP.keys())]
    if len(outs):
        fig.add_trace(go.Scatter(
            x=outs["x_ft"], y=outs["y_ft"], mode="markers", name="Out",
            marker=dict(size=8, color="#667788", opacity=0.6),
            text=outs["pitch_description"], hovertemplate="Out<br>%{text}<extra></extra>",
        ))
    for etype, color in HIT_COLORS_MAP.items():
        grp = bip[bip["event_type"] == etype]
        if len(grp):
            fig.add_trace(go.Scatter(
                x=grp["x_ft"], y=grp["y_ft"], mode="markers",
                name=etype.replace("_", " ").title(),
                marker=dict(size=11, color=color, line=dict(color="white", width=1)),
                text=grp["pitch_description"],
                hovertemplate=f"{etype.replace('_',' ').title()}<br>" + "%{text}<extra></extra>",
            ))

    fig.update_xaxes(range=[-370, 370], visible=False)
    fig.update_yaxes(range=[-30, 430], visible=False, scaleanchor="x", scaleratio=1)
    return _base_layout(fig, "Hit Spray Chart", height=420)


# ─────────────────────────────────────────────────────────────────────────────
# Pitch location / zone chart
# ─────────────────────────────────────────────────────────────────────────────

def zone_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()

    if df is None or df.empty or "px" not in df.columns:
        return _base_layout(fig, "Pitch Locations — no data", height=420)

    sz_top = df["sz_top"].mean()
    sz_bot = df["sz_bot"].mean()

    for pdesc, grp in df.groupby("pitch_description"):
        color = PITCH_COLORS.get(str(pdesc), "#AAAAAA")
        hard_hit = grp[grp["launch_speed"] >= 95]
        fig.add_trace(go.Scatter(
            x=grp["px"], y=grp["pz"], mode="markers", name=shorten_pitch(pdesc),
            marker=dict(size=10, color=color, line=dict(color="white", width=0.5), opacity=0.85),
            text=grp["play_description"], hovertemplate="%{text}<extra></extra>",
        ))
        if len(hard_hit):
            fig.add_trace(go.Scatter(
                x=hard_hit["px"], y=hard_hit["pz"], mode="markers", showlegend=False,
                marker=dict(size=22, color="rgba(255,255,255,0.25)", line=dict(width=0)),
                hoverinfo="skip",
            ))

    fig.add_shape(type="rect", x0=SZ_LEFT, x1=SZ_RIGHT, y0=sz_bot, y1=sz_top,
                  line=dict(color="white", width=2))
    for i in (1, 2):
        fig.add_shape(type="line", x0=SZ_LEFT + i * (SZ_RIGHT - SZ_LEFT) / 3, x1=SZ_LEFT + i * (SZ_RIGHT - SZ_LEFT) / 3,
                      y0=sz_bot, y1=sz_top, line=dict(color="#555577", width=1, dash="dot"))
        fig.add_shape(type="line", y0=sz_bot + i * (sz_top - sz_bot) / 3, y1=sz_bot + i * (sz_top - sz_bot) / 3,
                      x0=SZ_LEFT, x1=SZ_RIGHT, line=dict(color="#555577", width=1, dash="dot"))

    fig.update_xaxes(range=[-2.8, 2.8], title="Horizontal location (ft) — catcher's view")
    fig.update_yaxes(range=[0.5, 5.8], title="Vertical location (ft)", scaleanchor="x", scaleratio=1)
    return _base_layout(fig, "Pitch Locations (white glow = hard hit ≥95 mph)", height=420)


# ─────────────────────────────────────────────────────────────────────────────
# Pitch mix bar chart
# ─────────────────────────────────────────────────────────────────────────────

def pitch_mix_chart(pitch_table: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if pitch_table is None or pitch_table.empty:
        return _base_layout(fig, "Pitch Usage — no data", height=380)

    pt = pitch_table.sort_values("usage_pct")
    fig.add_trace(go.Bar(
        y=pt["pitch_type"], x=pt["usage_pct"], orientation="h",
        marker=dict(color=pt["color"]),
        text=[f"{u:.0f}%  |  Sw {s:.0f}%  |  Wh {w:.0f}%" for u, s, w in
              zip(pt["usage_pct"], pt["swing_pct"], pt["whiff_pct"])],
        textposition="outside", textfont=dict(color="white", size=11),
        hovertemplate="%{y}: %{x:.1f}%%<extra></extra>",
    ))
    fig.update_xaxes(title="Usage %", range=[0, max(pt["usage_pct"].max() * 1.35, 10)])
    return _base_layout(fig, "Pitch Usage | Swing% | Whiff%", height=max(320, 60 + 40 * len(pt)))


# ─────────────────────────────────────────────────────────────────────────────
# Exit velocity vs launch angle
# ─────────────────────────────────────────────────────────────────────────────

def ev_la_scatter(enriched_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    bip = enriched_df[enriched_df["launch_speed"].notna() & enriched_df["launch_angle"].notna()]
    if bip.empty:
        return _base_layout(fig, "Exit Velocity vs Launch Angle — no data", height=440)

    # Sweet-spot band
    fig.add_shape(type="rect", x0=8, x1=32, y0=0, y1=125, fillcolor="rgba(77,163,255,0.08)",
                  line=dict(width=0), layer="below")

    outs = bip[~bip["event_type"].isin(HIT_COLORS_MAP.keys())]
    fig.add_trace(go.Scatter(x=outs["launch_angle"], y=outs["launch_speed"], mode="markers",
                              name="Out", marker=dict(size=7, color="#667788", opacity=0.6)))
    for etype, color in HIT_COLORS_MAP.items():
        grp = bip[bip["event_type"] == etype]
        if len(grp):
            fig.add_trace(go.Scatter(x=grp["launch_angle"], y=grp["launch_speed"], mode="markers",
                                      name=etype.replace("_", " ").title(),
                                      marker=dict(size=9, color=color, line=dict(color="white", width=0.5))))

    fig.update_xaxes(title="Launch Angle (°)", range=[-90, 90])
    fig.update_yaxes(title="Exit Velocity (mph)", range=[0, 125])
    return _base_layout(fig, "Exit Velocity vs Launch Angle (shaded = sweet-spot 8°–32°)", height=460)


# ─────────────────────────────────────────────────────────────────────────────
# Plate discipline zone heatmap
# ─────────────────────────────────────────────────────────────────────────────

def discipline_heatmap(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if df is None or df.empty:
        return _base_layout(fig, "Swing Rate by Zone — no data", height=420)

    d = df.copy()
    d["is_swing_b"] = d["is_swing"].fillna(False).astype(bool)

    # Grid is built FROM the strike zone boundaries (not an independent fixed
    # range), so the middle 3x3 cells exactly match the zone outline instead
    # of the box cutting across cells at arbitrary points.
    sz_top = d["sz_top"].mean()
    sz_bot = d["sz_bot"].mean()
    col_w = (SZ_RIGHT - SZ_LEFT) / 3
    row_h = (sz_top - sz_bot) / 3
    x_edges = np.array([SZ_LEFT - col_w, SZ_LEFT, SZ_LEFT + col_w, SZ_RIGHT - col_w, SZ_RIGHT, SZ_RIGHT + col_w])
    y_edges = np.array([sz_bot - row_h, sz_bot, sz_bot + row_h, sz_top - row_h, sz_top, sz_top + row_h])
    n_bx, n_by = 5, 5
    x_centers = (x_edges[:-1] + x_edges[1:]) / 2
    y_centers = (y_edges[:-1] + y_edges[1:]) / 2

    grid = np.full((n_by, n_bx), np.nan)
    counts = np.zeros((n_by, n_bx), dtype=int)
    for i in range(n_by):
        for j in range(n_bx):
            mask = (d["px"] >= x_edges[j]) & (d["px"] < x_edges[j + 1]) & \
                   (d["pz"] >= y_edges[i]) & (d["pz"] < y_edges[i + 1])
            cell = d[mask]
            counts[i, j] = len(cell)
            if len(cell):
                grid[i, j] = cell["is_swing_b"].mean()

    text = [[f"{grid[i,j]*100:.0f}%" if counts[i, j] > 0 else "" for j in range(n_bx)] for i in range(n_by)]
    fig.add_trace(go.Heatmap(
        x=x_centers, y=y_centers, z=grid, text=text, texttemplate="%{text}",
        colorscale=[[0, "#0d1b2a"], [0.4, "#1a4a8a"], [0.75, "#e06000"], [1, "#ff2200"]],
        zmin=0, zmax=1, colorbar=dict(title="Swing%", tickfont=dict(color=MUTED)),
    ))
    fig.add_shape(type="rect", x0=SZ_LEFT, x1=SZ_RIGHT, y0=sz_bot, y1=sz_top,
                  line=dict(color="white", width=2))
    fig.update_xaxes(title="Horizontal (ft)")
    fig.update_yaxes(title="Vertical (ft)", scaleanchor="x", scaleratio=1)
    return _base_layout(fig, "Swing Rate by Zone", height=420)


# ─────────────────────────────────────────────────────────────────────────────
# Count-based swing rate
# ─────────────────────────────────────────────────────────────────────────────

def count_heatmap(metric_grid: np.ndarray, counts: np.ndarray, label: str = "Swing%",
                   title: str = "Swing Rate by Count", hover_detail: np.ndarray = None,
                   height: int = 420) -> go.Figure:
    fig = go.Figure()
    text = [[f"{metric_grid[s,b]*100:.0f}%<br>({counts[s,b]}p)" if counts[s, b] > 0 and not np.isnan(metric_grid[s, b])
             else (f"{counts[s,b]}p" if counts[s, b] > 0 else "")
             for b in range(4)] for s in range(3)]
    heatmap_kwargs = dict(
        x=["0B", "1B", "2B", "3B"], y=["0S", "1S", "2S"], z=metric_grid,
        text=text, texttemplate="%{text}",
        colorscale=[[0, "#0d1b2a"], [0.4, "#1a4a8a"], [0.75, "#e06000"], [1, "#ff2200"]],
        zmin=0, zmax=1, colorbar=dict(title=label, tickfont=dict(color=MUTED)),
    )
    if hover_detail is not None:
        heatmap_kwargs["customdata"] = hover_detail
        heatmap_kwargs["hovertemplate"] = "%{customdata}<extra></extra>"
    fig.add_trace(go.Heatmap(**heatmap_kwargs))
    return _base_layout(fig, title, height=height)


# ─────────────────────────────────────────────────────────────────────────────
# Contact profile (in zone vs out of zone)
# ─────────────────────────────────────────────────────────────────────────────

CONTACT_OUTCOME_COLORS = {
    "Whiff": "#69758c",
    "Foul Ball": "#fb923c",
    "In Play": "#2dd4bf",
}


def contact_profile_chart(profile_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if profile_df is None or profile_df.empty:
        return _base_layout(fig, "Contact Profile by Zone — no swings in this filter", height=380)

    zone_groups = [zg for zg in ["In Zone", "Out of Zone"] if zg in profile_df["zone_group"].unique()]
    if not zone_groups:
        return _base_layout(fig, "Contact Profile by Zone — no swings in this filter", height=380)

    n_by_zone = {zg: profile_df[profile_df["zone_group"] == zg]["n"].sum() for zg in zone_groups}

    for outcome in ["Whiff", "Foul Ball", "In Play"]:
        ys, texts = [], []
        for zg in zone_groups:
            row = profile_df[(profile_df["zone_group"] == zg) & (profile_df["outcome"] == outcome)]
            pct = float(row["pct"].iloc[0]) if len(row) else 0.0
            ys.append(pct)
            texts.append(f"{pct:.0f}%" if pct >= 6 else "")
        fig.add_trace(go.Bar(
            x=[f"{zg}<br>({n_by_zone[zg]} swings)" for zg in zone_groups], y=ys, name=outcome,
            marker=dict(color=CONTACT_OUTCOME_COLORS[outcome], line=dict(color="rgba(255,255,255,0.25)", width=1)),
            text=texts, textposition="inside", insidetextanchor="middle",
            textfont=dict(color="#12122a", size=12, family="Inter, sans-serif"),
            hovertemplate=f"{outcome}: " + "%{y:.1f}%<extra></extra>",
        ))

    fig.update_layout(barmode="stack")
    fig.update_yaxes(title="% of swings", range=[0, 100])
    return _base_layout(fig, "Contact Profile: In Zone vs Out of Zone (caught foul tips count as whiffs)", height=440)


# ─────────────────────────────────────────────────────────────────────────────
# Percentile bar (Savant-style)
# ─────────────────────────────────────────────────────────────────────────────

def percentile_bars(pct_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    plot_df = pct_df[pct_df["percentile"].notna()].copy()
    if plot_df.empty:
        fig.add_annotation(text="Not enough league data yet", showarrow=False,
                            font=dict(color=MUTED, size=14), xref="paper", yref="paper", x=0.5, y=0.5)
        return _base_layout(fig, "", height=380)

    # A vivid, continuous gradient instead of flat gray-centered buckets —
    # same blue-is-below-average / red-is-elite convention as before, but
    # smoothly interpolated through a warm gold midpoint so nothing in the
    # middle of the pack renders as dull gray.
    _STOPS = [
        (0, (47, 105, 176)),     # #2f69b0 — sapphire blue (jewel-tone family, "bad")
        (25, (79, 155, 181)),    # #4f9bb5 — teal-blue
        (50, (212, 162, 74)),    # #d4a24a — topaz gold (average)
        (75, (214, 108, 58)),    # #d66c3a — burnt orange
        (100, (196, 30, 38)),    # #c41e26 — true red, not pink ("elite")
    ]

    def color_for(p: float) -> str:
        p = max(0.0, min(100.0, p))
        for (p0, c0), (p1, c1) in zip(_STOPS, _STOPS[1:]):
            if p0 <= p <= p1:
                t = (p - p0) / (p1 - p0) if p1 != p0 else 0
                r = round(c0[0] + (c1[0] - c0[0]) * t)
                g = round(c0[1] + (c1[1] - c0[1]) * t)
                b = round(c0[2] + (c1[2] - c0[2]) * t)
                return f"rgb({r},{g},{b})"
        return "rgb(196,30,38)"

    plot_df = plot_df.iloc[::-1]
    fig.add_trace(go.Bar(
        y=plot_df["metric"], x=plot_df["percentile"], orientation="h",
        marker=dict(
            color=[color_for(p) for p in plot_df["percentile"]],
            line=dict(color="rgba(255,255,255,0.35)", width=1),
        ),
        text=[f"{p:.0f}" for p in plot_df["percentile"]],
        textposition="outside", textfont=dict(color="white", size=13, family="Inter, sans-serif"),
        hovertemplate="%{y}: %{x:.0f}th percentile<extra></extra>",
    ))
    fig.add_vline(x=50, line=dict(color="rgba(255,255,255,0.35)", dash="dash", width=1.5))
    fig.update_xaxes(title="Percentile vs qualified hitters", range=[0, 108])
    return _base_layout(fig, "", height=max(340, 45 * len(plot_df)))


# ─────────────────────────────────────────────────────────────────────────────
# Rolling trend
# ─────────────────────────────────────────────────────────────────────────────

def multi_rolling_trend_chart(trend_df: pd.DataFrame, stat_names: list, window: int,
                                format_map: dict = None) -> go.Figure:
    """Up to 3 stats plotted together over the same rolling PA window. All
    rate/percentage stats (AVG, K%, Whiff%, etc — everything except Avg
    Exit Velo) share one 0-1 axis, since they're all naturally fractions
    even though some are conventionally displayed as .XXX and others as a
    percentage; the hover text formats each trace correctly regardless of
    what the shared axis ticks show. A "num1" stat (e.g. Avg Exit Velo) is
    on a different scale entirely (mph, not a fraction), so it gets its
    own secondary axis whenever it's one of the selected stats.

    format_map: {stat_name: "rate3"|"pct"|"num1"}, e.g. stats.TREND_STAT_FORMAT
    or stats_pitching.PITCHER_TREND_STAT_FORMAT. Defaults to
    stats.TREND_STAT_FORMAT's categories under the original hardcoded
    names if not given, so existing (Batter Dashboard) callers are
    unaffected — this parameter exists so a caller with differently-named
    stats (e.g. the Pitcher Dashboard's "AVG Against" instead of "AVG")
    can supply the matching format for its own names instead of the
    hover/axis logic silently defaulting to the wrong format for a name
    it doesn't recognize.
    """
    fig = go.Figure()
    if trend_df is None or trend_df.empty or not stat_names:
        return _base_layout(fig, "Rolling Trend — not enough data yet", height=420)

    if format_map is None:
        format_map = {
            "AVG": "rate3", "OBP": "rate3", "SLG": "rate3", "OPS": "rate3", "ISO": "rate3", "BABIP": "rate3",
            "Avg Exit Velo": "num1",
        }

    line_colors = [ACCENT, "#ff9f43", "#c2447a"]
    has_velo = any(format_map.get(n) == "num1" for n in stat_names)

    for i, name in enumerate(stat_names):
        if name not in trend_df.columns:
            continue
        fmt = format_map.get(name, "pct")
        is_velo = fmt == "num1"
        hover_fmt = "%{y:.1f} mph" if is_velo else ("%{y:.3f}" if fmt == "rate3" else "%{y:.1%}")
        fig.add_trace(go.Scatter(
            x=trend_df["game_date"], y=trend_df[name], mode="lines", name=name,
            line=dict(color=line_colors[i % len(line_colors)], width=2.2),
            yaxis="y2" if is_velo else "y",
            hovertemplate=f"{name}: {hover_fmt}<extra></extra>",
            connectgaps=False,
        ))

    layout_kwargs = dict(yaxis=dict(title="Rate", tickformat=".0%", gridcolor=GRID))
    if has_velo:
        layout_kwargs["yaxis2"] = dict(title="Exit Velo (mph)", overlaying="y", side="right", showgrid=False)

    fig.update_layout(**layout_kwargs)
    return _base_layout(fig, f"Rolling {window}-PA Trend", height=440)


def rolling_trend_chart(trend_df: pd.DataFrame, window: int) -> go.Figure:
    fig = go.Figure()
    if trend_df is None or trend_df.empty:
        return _base_layout(fig, "Rolling Trend — not enough plate appearances yet", height=400)

    fig.add_trace(go.Scatter(x=trend_df["game_date"], y=trend_df["roll_avg"], mode="lines",
                              name=f"Rolling AVG ({window} PA)", line=dict(color=ACCENT, width=2)))
    fig.add_trace(go.Scatter(x=trend_df["game_date"], y=trend_df["roll_k_pct"] / 100, mode="lines",
                              name="Rolling K%", line=dict(color="#ff7700", width=1.5, dash="dot"), yaxis="y2"))
    fig.add_trace(go.Scatter(x=trend_df["game_date"], y=trend_df["roll_bb_pct"] / 100, mode="lines",
                              name="Rolling BB%", line=dict(color="#00cc88", width=1.5, dash="dot"), yaxis="y2"))

    fig.update_layout(
        yaxis=dict(title="Rolling AVG", tickformat=".3f", gridcolor=GRID),
        yaxis2=dict(title="Rolling K% / BB%", overlaying="y", side="right", tickformat=".0%", showgrid=False),
    )
    return _base_layout(fig, f"Rolling {window}-PA Trend", height=420)


def team_run_trend_chart(run_df: pd.DataFrame, window: int = 10) -> go.Figure:
    """Rolling runs scored vs. runs allowed per game — the most direct visual
    answer to 'is this team hot or cold right now'. Line crossovers (scoring
    trend dropping below the allowed trend) usually line up with losing
    stretches."""
    fig = go.Figure()
    if run_df is None or run_df.empty:
        return _base_layout(fig, "Runs Scored vs Allowed — no game-score data available", height=420)

    fig.add_trace(go.Scatter(x=run_df["game_date"], y=run_df["roll_runs_scored"], mode="lines",
                              name=f"Runs Scored ({window}-game avg)", line=dict(color="#2dd4bf", width=2.5)))
    fig.add_trace(go.Scatter(x=run_df["game_date"], y=run_df["roll_runs_allowed"], mode="lines",
                              name=f"Runs Allowed ({window}-game avg)", line=dict(color="#ff5c5c", width=2.5)))
    fig.add_trace(go.Bar(x=run_df["game_date"], y=run_df["team_runs"], name="Runs Scored (game)",
                          marker=dict(color="rgba(45,212,191,0.18)"), showlegend=False))
    fig.add_trace(go.Bar(x=run_df["game_date"], y=run_df["opp_runs"], name="Runs Allowed (game)",
                          marker=dict(color="rgba(255,92,92,0.14)"), showlegend=False))

    fig.update_layout(barmode="overlay")
    fig.update_yaxes(title="Runs")
    return _base_layout(fig, f"Runs Scored vs. Allowed ({window}-game rolling average)", height=440)
