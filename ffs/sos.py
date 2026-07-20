from __future__ import annotations

import pandas as pd

from ffs import matchups


def opponents_by_team(
    schedule_df: pd.DataFrame,
    weeks: tuple[int, int] | None = None,
    regular_season_only: bool = True,
) -> pd.DataFrame:
    """Long-format table: one row per (team, week) with the team's opponent."""
    df = schedule_df
    if regular_season_only and "game_type" in df.columns:
        df = df[df["game_type"] == "REG"]
    if weeks is not None:
        lo, hi = weeks
        df = df[(df["week"] >= lo) & (df["week"] <= hi)]
    home = df[["season", "week", "home_team", "away_team"]].rename(
        columns={"home_team": "team", "away_team": "opponent"}
    )
    away = df[["season", "week", "away_team", "home_team"]].rename(
        columns={"away_team": "team", "home_team": "opponent"}
    )
    return (
        pd.concat([home, away], ignore_index=True)
        .sort_values(["team", "week"])
        .reset_index(drop=True)
    )


def team_sos(
    schedule_df: pd.DataFrame,
    scored_df: pd.DataFrame,
    position: str,
    ranking_season: int,
    weeks: tuple[int, int] | None = None,
) -> pd.DataFrame:
    """Per-team average opponent FP-allowed vs `position` over the given week range."""
    rankings = matchups.defense_ranking(
        scored_df, season=ranking_season, position=position
    )
    opp = opponents_by_team(schedule_df, weeks=weeks)
    merged = opp.merge(
        rankings[["defense", "fp_allowed_pg"]],
        left_on="opponent",
        right_on="defense",
        how="left",
    )
    result = (
        merged.groupby("team")
        .agg(
            games=("week", "count"),
            avg_opp_fp_allowed=("fp_allowed_pg", "mean"),
        )
        .reset_index()
    )
    league_avg = result["avg_opp_fp_allowed"].mean()
    result["sos_delta"] = result["avg_opp_fp_allowed"] - league_avg
    result["sos_rank_easiest"] = (
        result["avg_opp_fp_allowed"].rank(ascending=False, method="min").astype(int)
    )
    return result.sort_values("avg_opp_fp_allowed", ascending=False).reset_index(drop=True)
