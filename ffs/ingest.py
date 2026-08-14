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


def fetch_team_stats(season: int) -> pd.DataFrame:
    import nflreadpy as nfl

    return nfl.load_team_stats([season]).to_pandas()


def save_team_stats(df: pd.DataFrame, season: int) -> None:
    path = config.ensure_parent(config.team_stats_path(season))
    df.to_parquet(path, index=False)


def load_team_stats(season: int) -> pd.DataFrame:
    return pd.read_parquet(config.team_stats_path(season))


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


def fetch_injuries(season: int) -> pd.DataFrame:
    import nflreadpy as nfl

    return nfl.load_injuries([season]).to_pandas()


def save_injuries(df: pd.DataFrame, season: int) -> None:
    path = config.ensure_parent(config.injuries_path(season))
    df.to_parquet(path, index=False)


def load_injuries(season: int) -> pd.DataFrame:
    return pd.read_parquet(config.injuries_path(season))


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


_FFC_SCORING_ALIAS = {"standard": "standard", "ppr": "ppr", "half_ppr": "half-ppr"}


def fetch_ffc_adp(
    scoring: str = "standard", teams: int = 12, year: int | None = None
) -> pd.DataFrame:
    """Fantasy Football Calculator ADP — real 12-team mock drafts, updated daily."""
    import requests

    ffc_scoring = _FFC_SCORING_ALIAS.get(scoring, scoring)
    url = "https://fantasyfootballcalculator.com/api/v1/adp/" + ffc_scoring
    params: dict[str, int | str] = {"teams": teams, "position": "all"}
    if year is not None:
        params["year"] = year
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    df = pd.DataFrame(payload["players"])
    meta = payload.get("meta", {})
    df.attrs["ffc_meta"] = meta
    return df


def save_ffc_adp(df: pd.DataFrame) -> None:
    path = config.ensure_parent(config.ffc_adp_path())
    df.to_parquet(path, index=False)


def load_ffc_adp() -> pd.DataFrame:
    return pd.read_parquet(config.ffc_adp_path())
