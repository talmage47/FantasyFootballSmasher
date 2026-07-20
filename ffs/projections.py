from __future__ import annotations

import pandas as pd

from ffs import matchups


def player_baseline(
    scored_df: pd.DataFrame,
    up_to: tuple[int, int],
    window: int = 8,
    min_season: int | None = None,
    regular_season_only: bool = True,
) -> pd.DataFrame:
    """Per player: mean fantasy points over their last `window` games through (season, week).

    `min_season` filters out ancient history so retired players don't produce baselines.
    """
    df = scored_df
    if regular_season_only and "season_type" in df.columns:
        df = df[df["season_type"] == "REG"]
    if min_season is not None:
        df = df[df["season"] >= min_season]
    df = df[
        (df["season"] < up_to[0])
        | ((df["season"] == up_to[0]) & (df["week"] <= up_to[1]))
    ].sort_values(["player_id", "season", "week"])
    tail = df.groupby("player_id").tail(window)
    return (
        tail.groupby(["player_id", "player_display_name", "position"], dropna=False)
        .agg(
            baseline_ppg=("fantasy_points_ffs", "mean"),
            games_in_window=("week", "count"),
            team=("team", "last"),
        )
        .reset_index()
    )


def project_week(
    scored_df: pd.DataFrame,
    schedule_df: pd.DataFrame,
    target_season: int,
    target_week: int,
    window: int = 8,
    rankings_season: int | None = None,
    positions: tuple[str, ...] = matchups.SKILL_POSITIONS,
    min_games: int = 3,
) -> pd.DataFrame:
    """Project target_week fantasy points as baseline_ppg × opponent adjustment factor."""
    if rankings_season is None:
        rankings_season = target_season - 1 if target_week == 1 else target_season

    if target_week == 1:
        up_to = (target_season - 1, 99)
    else:
        up_to = (target_season, target_week - 1)

    baselines = player_baseline(
        scored_df, up_to=up_to, window=window, min_season=target_season - 1
    )
    baselines = baselines[
        baselines["position"].isin(positions)
        & (baselines["games_in_window"] >= min_games)
    ]

    target_games = schedule_df[
        (schedule_df["season"] == target_season) & (schedule_df["week"] == target_week)
    ]
    if target_games.empty:
        raise ValueError(f"No games scheduled for {target_season} week {target_week}")
    opp = pd.concat(
        [
            target_games[["home_team", "away_team"]].rename(
                columns={"home_team": "team", "away_team": "opponent"}
            ),
            target_games[["away_team", "home_team"]].rename(
                columns={"away_team": "team", "home_team": "opponent"}
            ),
        ],
        ignore_index=True,
    )

    frames = []
    for pos in positions:
        pos_baselines = baselines[baselines["position"] == pos]
        if pos_baselines.empty:
            continue
        rankings = matchups.defense_ranking(
            scored_df, season=rankings_season, position=pos
        )
        league_avg = rankings["fp_allowed_pg"].mean()
        rankings = rankings.assign(opp_factor=rankings["fp_allowed_pg"] / league_avg)
        merged = pos_baselines.merge(opp, on="team", how="left").merge(
            rankings[["defense", "opp_factor"]],
            left_on="opponent",
            right_on="defense",
            how="left",
        )
        merged["projection"] = merged["baseline_ppg"] * merged["opp_factor"]
        frames.append(merged)

    result = pd.concat(frames, ignore_index=True).dropna(subset=["projection"])
    return result.sort_values("projection", ascending=False).reset_index(drop=True)
