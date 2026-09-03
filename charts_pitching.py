"""
charts_pitching.py
───────────────────
Charts specific to pitcher analysis (velocity, pitch shape/movement, release
point). Everything else (zone chart, spray/EV-LA against, discipline heatmap,
count heatmap, percentile bars, rolling trend shape) reuses charts.py
directly — those functions only care about column names, not which player
the pitch log was filtered to.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from charts import BG, GRID, MUTED, PANEL, ACCENT, _base_layout
from stats import PITCH_COLORS, shorten_pitch


def velocity_by_pitch_chart(df: pd.DataFrame) -> go.Figure:
    """Box plot of pitch speed per pitch type — shows both the average velo
    and how consistent it is (tight box = repeatable release)."""
    fig = go.Figure()
    if df is None or df.empty or "start_speed" not in df.columns:
        return _base_layout(fig, "Velocity by Pitch Type — no data", height=460)

    order = df.groupby("pitch_description")["start_speed"].mean().sort_values(ascending=False).index
    for pdesc in order:
        grp = df[df["pitch_description"] == pdesc]
        color = PITCH_COLORS.get(str(pdesc), "#AAAAAA")
        fig.add_trace(go.Box(
            y=grp["start_speed"], name=shorten_pitch(pdesc),
            marker=dict(color=color), line=dict(color=color),
            boxmean=True,
        ))
    fig.update_yaxes(title="Velocity (mph)")
    return _base_layout(fig, "Velocity Distribution by Pitch Type", height=460)


def movement_plot(df: pd.DataFrame) -> go.Figure:
    """The classic pitcher's-eye-view movement chart: induced vertical break
    vs. horizontal break, colored by pitch type. Distinct, well-separated
    clusters usually mean a pitcher has good separation between offerings;
    overlapping clusters can mean two pitches look similar out of the hand."""
    fig = go.Figure()
    if df is None or df.empty or "ivb" not in df.columns or "hb" not in df.columns:
        return _base_layout(fig, "Pitch Movement — no data", height=460)

    d = df.dropna(subset=["ivb", "hb"])
    if d.empty:
        return _base_layout(fig, "Pitch Movement — no movement data for this filter", height=460)

    fig.add_hline(y=0, line=dict(color=GRID, width=1))
    fig.add_vline(x=0, line=dict(color=GRID, width=1))

    for pdesc, grp in d.groupby("pitch_description"):
        color = PITCH_COLORS.get(str(pdesc), "#AAAAAA")
        fig.add_trace(go.Scatter(
            x=grp["hb"], y=grp["ivb"], mode="markers", name=shorten_pitch(pdesc),
            marker=dict(size=8, color=color, opacity=0.7, line=dict(color="white", width=0.3)),
        ))
        fig.add_trace(go.Scatter(
            x=[grp["hb"].mean()], y=[grp["ivb"].mean()], mode="markers", showlegend=False,
            marker=dict(size=16, color=color, line=dict(color="white", width=2)),
            hovertemplate=f"{shorten_pitch(pdesc)} avg<extra></extra>",
        ))

    fig.update_xaxes(title="Horizontal Break (in) - glove side vs. arm side")
    fig.update_yaxes(title="Induced Vertical Break (in) - drop vs. rise")
    return _base_layout(fig, "Pitch Movement (large dot = average shape per pitch)", height=520)


def release_point_chart(df: pd.DataFrame) -> go.Figure:
    """Release point consistency by pitch type — a release point that
    drifts a lot within a pitch type, or between pitch types, is often
    exactly what tips hitters off."""
    fig = go.Figure()
    if df is None or df.empty or "x0" not in df.columns or "z0" not in df.columns:
        return _base_layout(fig, "Release Point — no data", height=460)

    d = df.dropna(subset=["x0", "z0"])
    if d.empty:
        return _base_layout(fig, "Release Point — no release-point data for this filter", height=460)

    for pdesc, grp in d.groupby("pitch_description"):
        color = PITCH_COLORS.get(str(pdesc), "#AAAAAA")
        fig.add_trace(go.Scatter(
            x=grp["x0"], y=grp["z0"], mode="markers", name=shorten_pitch(pdesc),
            marker=dict(size=7, color=color, opacity=0.6, line=dict(color="white", width=0.3)),
        ))

    fig.update_xaxes(title="Horizontal Release (ft) — catcher's view")
    fig.update_yaxes(title="Vertical Release (ft)")
    return _base_layout(fig, "Release Point by Pitch Type", height=460)


def pitch_mix_by_count_chart(mix_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if mix_df is None or mix_df.empty:
        return _base_layout(fig, "Pitch Mix by Count — no data", height=420)

    situations = ["Ahead (pitcher)", "Even", "Behind (pitcher)"]
    pitch_types = mix_df["pitch_type"].unique().tolist()
    color_map = {}
    for full, color in PITCH_COLORS.items():
        short = shorten_pitch(full)
        if short in pitch_types:
            color_map[short] = color

    for pt in pitch_types:
        ys = []
        for sit in situations:
            row = mix_df[(mix_df["situation"] == sit) & (mix_df["pitch_type"] == pt)]
            ys.append(row["usage_pct"].iloc[0] if len(row) else 0)
        fig.add_trace(go.Bar(x=situations, y=ys, name=pt, marker=dict(color=color_map.get(pt, "#AAAAAA"))))

    fig.update_layout(barmode="stack")
    fig.update_yaxes(title="Usage %", range=[0, 100])
    return _base_layout(fig, "Pitch Mix by Count Situation", height=440)


def rolling_trend_pitcher_chart(trend_df: pd.DataFrame, window: int) -> go.Figure:
    fig = go.Figure()
    if trend_df is None or trend_df.empty:
        return _base_layout(fig, "Rolling Trend — not enough batters faced yet", height=400)

    fig.add_trace(go.Scatter(x=trend_df["game_date"], y=trend_df["roll_avg_against"], mode="lines",
                              name=f"Rolling AVG-against ({window} PA)", line=dict(color=ACCENT, width=2)))
    fig.add_trace(go.Scatter(x=trend_df["game_date"], y=trend_df["roll_k_pct"] / 100, mode="lines",
                              name="Rolling K%", line=dict(color="#00cc88", width=1.5, dash="dot"), yaxis="y2"))
    fig.add_trace(go.Scatter(x=trend_df["game_date"], y=trend_df["roll_bb_pct"] / 100, mode="lines",
                              name="Rolling BB%", line=dict(color="#ff7700", width=1.5, dash="dot"), yaxis="y2"))

    fig.update_layout(
        yaxis=dict(title="Rolling AVG-against", tickformat=".3f", gridcolor=GRID),
        yaxis2=dict(title="Rolling K% / BB%", overlaying="y", side="right", tickformat=".0%", showgrid=False),
    )
    return _base_layout(fig, f"Rolling {window}-PA Trend (Against)", height=420)
