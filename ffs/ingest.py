from __future__ import annotations

import pandas as pd

from ffs import config


def fetch_weekly(season: int) -> pd.DataFrame:
    import nflreadpy as nfl

    return nfl.load_player_stats([season]).to_pandas()


def save_weekly(df: pd.DataFrame, season: int) -> None:
    path = config.ensure_parent(config.weekly_raw_path(season))
    df.to_parquet(path, index=False)


def load_weekly(season: int) -> pd.DataFrame:
    return pd.read_parquet(config.weekly_raw_path(season))


def fetch_schedules(season: int) -> pd.DataFrame:
    import nflreadpy as nfl

    return nfl.load_schedules([season]).to_pandas()


def save_schedules(df: pd.DataFrame, season: int) -> None:
    path = config.ensure_parent(config.schedules_path(season))
    df.to_parquet(path, index=False)


def load_schedules(season: int) -> pd.DataFrame:
    return pd.read_parquet(config.schedules_path(season))


def fetch_rosters(season: int) -> pd.DataFrame:
    import nflreadpy as nfl

    return nfl.load_rosters([season]).to_pandas()


def save_rosters(df: pd.DataFrame, season: int) -> None:
    path = config.ensure_parent(config.rosters_path(season))
    df.to_parquet(path, index=False)


def load_rosters(season: int) -> pd.DataFrame:
    return pd.read_parquet(config.rosters_path(season))


def fetch_depth_charts(season: int) -> pd.DataFrame:
    import nflreadpy as nfl

    return nfl.load_depth_charts([season]).to_pandas()


def save_depth_charts(df: pd.DataFrame, season: int) -> None:
    path = config.ensure_parent(config.depth_charts_path(season))
    df.to_parquet(path, index=False)


def load_depth_charts(season: int) -> pd.DataFrame:
    return pd.read_parquet(config.depth_charts_path(season))


def fetch_adp() -> pd.DataFrame:
    """FantasyPros redraft-overall consensus rankings joined to gsis_id."""
    import nflreadpy as nfl

    rankings = nfl.load_ff_rankings().to_pandas()
    ids = nfl.load_ff_playerids().to_pandas()

    overall = (
        rankings[rankings["page_type"] == "redraft-overall"][
            ["id", "player", "pos", "team", "ecr", "sd", "best", "worst", "scrape_date"]
        ]
        .rename(columns={"id": "fantasypros_id", "ecr": "adp"})
        .copy()
    )
    overall["fantasypros_id"] = overall["fantasypros_id"].astype(str)

    id_map = ids[["fantasypros_id", "gsis_id"]].dropna(subset=["fantasypros_id"]).copy()
    id_map["fantasypros_id"] = id_map["fantasypros_id"].astype(str)

    merged = overall.merge(id_map, on="fantasypros_id", how="left")
    return merged.rename(columns={"gsis_id": "player_id"})


def save_adp(df: pd.DataFrame) -> None:
    path = config.ensure_parent(config.adp_path())
    df.to_parquet(path, index=False)


def load_adp() -> pd.DataFrame:
    return pd.read_parquet(config.adp_path())
