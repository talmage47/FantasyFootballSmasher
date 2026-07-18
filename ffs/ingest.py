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
