from __future__ import annotations

import pandas as pd

from ffs import career as career_mod, config, ingest

DEFAULT_LOOKBACK_SEASONS: int = 4
INJURY_PRONE_THRESHOLD: float = 0.20
_MIN_ACTIVE_GAMES_PER_SEASON: int = 4


def _regular_season_games(season: int) -> int:
    return 17 if season >= 2021 else 16


def player_durability(
    lookback_seasons: int = DEFAULT_LOOKBACK_SEASONS,
    up_to_season: int | None = None,
    scored_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Per-player fraction of REG games missed due to injury across recent seasons.

    For each (player, season) in the lookback window where the player had at least
    `_MIN_ACTIVE_GAMES_PER_SEASON` REG games scored (proving they were on an NFL
    roster that year — filters out rookies without prior data and season-long IR
    starts), the missed fraction is:

        max(out_weeks_from_injury_report, possible_games − scored_games) / possible_games

    The `max` catches players who tore ACLs early and disappeared from weekly
    injury reports — the scored-games gap fills in for them.

    Returns columns: player_id, games_missed_pct (0..1), durable_seasons_n.
    Players with no qualifying seasons in the window are absent from the result
    (typical for rookies).
    """
    if scored_df is None:
        scored_df = career_mod.load_scored()
    if scored_df.empty:
        return pd.DataFrame(columns=["player_id", "games_missed_pct", "durable_seasons_n"])

    if "season_type" in scored_df.columns:
        scored_df = scored_df[scored_df["season_type"] == "REG"]

    latest = up_to_season if up_to_season is not None else int(scored_df["season"].max())
    seasons = list(range(latest - lookback_seasons + 1, latest + 1))

    scored_recent = scored_df[scored_df["season"].isin(seasons)]
    games_by_ps = (
        scored_recent.dropna(subset=["player_id"])
        .groupby(["player_id", "season"])
        .size()
        .reset_index(name="scored_games")
    )
    games_by_ps = games_by_ps[games_by_ps["scored_games"] >= _MIN_ACTIVE_GAMES_PER_SEASON]
    if games_by_ps.empty:
        return pd.DataFrame(columns=["player_id", "games_missed_pct", "durable_seasons_n"])

    out_frames = []
    for season in seasons:
        p = config.injuries_path(season)
        if not p.exists():
            continue
        inj = ingest.load_injuries(season)
        if "game_type" in inj.columns:
            inj = inj[inj["game_type"] == "REG"]
        outs = (
            inj[inj["report_status"] == "Out"]
            .dropna(subset=["gsis_id"])
            .drop_duplicates(subset=["gsis_id", "week"])
            .groupby("gsis_id")
            .size()
            .reset_index(name="out_weeks")
        )
        outs["season"] = season
        outs = outs.rename(columns={"gsis_id": "player_id"})
        out_frames.append(outs)
    out_by_ps = (
        pd.concat(out_frames, ignore_index=True)
        if out_frames
        else pd.DataFrame(columns=["player_id", "season", "out_weeks"])
    )

    joined = games_by_ps.merge(out_by_ps, on=["player_id", "season"], how="left")
    joined["out_weeks"] = joined["out_weeks"].fillna(0).astype(int)
    joined["possible_games"] = joined["season"].map(_regular_season_games)
    joined["gap"] = (joined["possible_games"] - joined["scored_games"]).clip(lower=0)
    joined["missed_this_season"] = joined[["out_weeks", "gap"]].max(axis=1)
    joined["missed_pct"] = joined["missed_this_season"] / joined["possible_games"]

    summary = (
        joined.groupby("player_id")
        .agg(
            games_missed_pct=("missed_pct", "mean"),
            durable_seasons_n=("season", "nunique"),
        )
        .reset_index()
    )
    return summary


def attach_durability(
    df: pd.DataFrame,
    durability_df: pd.DataFrame,
    threshold: float = INJURY_PRONE_THRESHOLD,
) -> pd.DataFrame:
    """Left-join games_missed_pct + durable_seasons_n + injury_prone onto a frame."""
    if "player_id" not in df.columns:
        out = df.copy()
        out["games_missed_pct"] = pd.NA
        out["durable_seasons_n"] = pd.NA
        out["injury_prone"] = False
        return out
    merged = df.merge(durability_df, on="player_id", how="left")
    merged["injury_prone"] = merged["games_missed_pct"].fillna(0) >= threshold
    return merged
