from __future__ import annotations

import pandas as pd

SKILL_POSITIONS = ("QB", "RB", "WR", "TE")


def points_allowed_by_game(
    scored_df: pd.DataFrame,
    positions: tuple[str, ...] = SKILL_POSITIONS,
    regular_season_only: bool = True,
) -> pd.DataFrame:
    """One row per (season, week, defense, position): total FP allowed."""
    df = scored_df
    if regular_season_only and "season_type" in df.columns:
        df = df[df["season_type"] == "REG"]
    df = df[df["position"].isin(positions)]
    grouped = (
        df.groupby(["season", "week", "opponent_team", "position"], dropna=False)[
            "fantasy_points_ffs"
        ]
        .sum()
        .reset_index()
        .rename(columns={"opponent_team": "defense", "fantasy_points_ffs": "fp_allowed"})
    )
    return grouped


def defense_ranking(
    scored_df: pd.DataFrame,
    season: int,
    position: str,
    last_n_weeks: int | None = None,
) -> pd.DataFrame:
    """Per-game FP allowed by each defense to `position`, ranked and league-relative."""
    per_game = points_allowed_by_game(scored_df, positions=(position,))
    per_game = per_game[per_game["season"] == season]
    if last_n_weeks is not None:
        max_week = per_game["week"].max()
        per_game = per_game[per_game["week"] > max_week - last_n_weeks]

    agg = (
        per_game.groupby("defense")
        .agg(games=("week", "nunique"), fp_allowed_total=("fp_allowed", "sum"))
        .reset_index()
    )
    agg["fp_allowed_pg"] = agg["fp_allowed_total"] / agg["games"]
    league_avg = agg["fp_allowed_pg"].mean()
    agg["vs_league"] = agg["fp_allowed_pg"] - league_avg
    agg["rank_easiest"] = agg["fp_allowed_pg"].rank(ascending=False, method="min").astype(int)
    return agg.sort_values("fp_allowed_pg", ascending=False).reset_index(drop=True)
