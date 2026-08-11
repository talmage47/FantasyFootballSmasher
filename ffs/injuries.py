from __future__ import annotations

import pandas as pd

AVAILABILITY_MULTIPLIER: dict[str, float] = {
    "Out": 0.0,
    "Doubtful": 0.25,
    "Questionable": 0.75,
}


def latest_injuries_per_player(
    injuries: pd.DataFrame,
    season: int | None = None,
    week: int | None = None,
) -> pd.DataFrame:
    """Return one row per gsis_id with an injury report.

    - If `week` is passed, filter to that exact (season, week) — the right
      choice for in-season lineup decisions (only this week's report matters).
    - If only `season` is passed, take each player's most recent week in that
      season — the right choice for preseason draft informational lookups.
    - If `season` isn't found in the data (offseason before nflreadpy has the
      new season), fall back to the latest season present.
    """
    df = injuries
    df = df[df["gsis_id"].notna()]
    if df.empty:
        return df.assign(player_id=pd.Series(dtype=str))
    if season is not None and (df["season"] == season).any():
        df = df[df["season"] == season]
    else:
        latest_season = df["season"].max()
        df = df[df["season"] == latest_season]
    if week is not None:
        df = df[df["week"] == week]
        if df.empty:
            return df.rename(columns={"gsis_id": "player_id"}).reset_index(drop=True)
        # A player can appear multiple times in a single (season, week) row set;
        # take the last (usually identical) row.
        latest = df.groupby("gsis_id", as_index=False).tail(1)
    else:
        latest = (
            df.sort_values(["gsis_id", "season", "week"])
            .groupby("gsis_id", as_index=False)
            .tail(1)
        )
    latest = latest.rename(columns={"gsis_id": "player_id"})
    keep = [
        "player_id", "season", "week", "report_status",
        "report_primary_injury", "practice_status",
    ]
    return latest[[c for c in keep if c in latest.columns]].reset_index(drop=True)


def availability_factor(status: pd.Series) -> pd.Series:
    """Map report_status → projection multiplier."""
    return status.map(AVAILABILITY_MULTIPLIER).fillna(1.0)


def attach_status(df: pd.DataFrame, latest: pd.DataFrame) -> pd.DataFrame:
    """Left-join injury_status onto a projections/draft frame keyed by player_id."""
    if latest.empty or "player_id" not in df.columns:
        out = df.copy()
        out["injury_status"] = pd.NA
        return out
    slim = latest[["player_id", "report_status"]].rename(
        columns={"report_status": "injury_status"}
    )
    return df.merge(slim, on="player_id", how="left")
