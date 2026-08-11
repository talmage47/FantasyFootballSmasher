from __future__ import annotations

import pandas as pd

from ffs import config


def load_scored(
    seasons: list[int] | None = None, ruleset: str = "standard"
) -> pd.DataFrame:
    """Load and concatenate scored weekly stats across seasons (including DST if present)."""
    if seasons is None:
        parent = config.PROCESSED_DIR / "weekly" / ruleset
        paths = sorted(parent.glob("*.parquet")) if parent.exists() else []
        dst_parent = config.PROCESSED_DIR / "dst" / ruleset
        dst_paths = sorted(dst_parent.glob("*.parquet")) if dst_parent.exists() else []
    else:
        paths = [
            config.weekly_scored_path(s, ruleset)
            for s in seasons
            if config.weekly_scored_path(s, ruleset).exists()
        ]
        dst_paths = [
            config.dst_scored_path(s, ruleset)
            for s in seasons
            if config.dst_scored_path(s, ruleset).exists()
        ]
    if not paths:
        raise FileNotFoundError(
            f"No scored data for ruleset {ruleset!r}. Run `ffs score` first."
        )
    frames = [pd.read_parquet(p) for p in paths] + [pd.read_parquet(p) for p in dst_paths]
    return pd.concat(frames, ignore_index=True)


def add_career_game_number(df: pd.DataFrame) -> pd.DataFrame:
    """Add a cumulative game number per player, spanning seasons."""
    df = df.sort_values(["player_id", "season", "week"]).copy()
    df["career_game"] = df.groupby("player_id").cumcount() + 1
    return df


def rolling_fantasy(df: pd.DataFrame, window: int) -> pd.DataFrame:
    """Add a rolling N-game fantasy-points average per player."""
    df = add_career_game_number(df)
    df["fp_roll"] = df.groupby("player_id")["fantasy_points_ffs"].transform(
        lambda s: s.rolling(window, min_periods=1).mean()
    )
    return df


def career_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per-player career aggregates: games, PPG, best week, seasons active."""
    grouped = df.groupby(
        ["player_id", "player_display_name", "position"], dropna=False
    )
    return grouped.agg(
        games=("week", "count"),
        seasons=("season", "nunique"),
        total=("fantasy_points_ffs", "sum"),
        ppg=("fantasy_points_ffs", "mean"),
        best_week=("fantasy_points_ffs", "max"),
        first_season=("season", "min"),
        last_season=("season", "max"),
    ).reset_index()
