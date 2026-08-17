from __future__ import annotations

import pandas as pd

FLEX_POSITIONS: tuple[str, ...] = ("RB", "WR", "TE")


def platoon_value(
    weekly_df: pd.DataFrame,
    anchor_player_id: str,
    candidate_pool_df: pd.DataFrame,
) -> pd.DataFrame:
    """Per-candidate platoon metrics relative to `anchor_player_id`.

    weekly_df: long-format per-player-per-week projections
      (from `projections.project_weekly`), with player_id, week, week_projection.
    candidate_pool_df: any frame with a `player_id` column; only candidates whose
      id appears here are scored.

    Returns one row per candidate:
      platoon_points_added — extra season points from starting max(anchor, cand) each week
      bye_covered — candidate plays on the anchor's bye
      weeks_candidate_starts — weeks where candidate outprojects anchor (or anchor is on bye)
    """
    anchor_rows = weekly_df[weekly_df["player_id"] == anchor_player_id]
    if anchor_rows.empty:
        raise ValueError(f"no weekly projections for anchor {anchor_player_id!r}")
    anchor_weeks = (
        anchor_rows.dropna(subset=["week"])
        .drop_duplicates("week")
        .set_index("week")["week_projection"]
    )
    anchor_total = float(anchor_weeks.sum())
    all_weeks = set(range(1, 19))
    anchor_bye = all_weeks - set(anchor_weeks.index)

    candidate_ids = set(candidate_pool_df["player_id"].dropna()) - {anchor_player_id}
    cand_weekly = weekly_df[weekly_df["player_id"].isin(candidate_ids)]
    if cand_weekly.empty:
        return pd.DataFrame(
            columns=[
                "player_id", "player_display_name", "position", "team",
                "platoon_points_added", "bye_covered", "weeks_candidate_starts",
            ]
        )

    rows = []
    for pid, group in cand_weekly.groupby("player_id"):
        cand_weeks = (
            group.dropna(subset=["week"]).drop_duplicates("week").set_index("week")["week_projection"]
        )
        merged = pd.concat(
            [anchor_weeks.rename("anchor"), cand_weeks.rename("cand")], axis=1
        )
        best = merged.max(axis=1)
        best_total = float(best.dropna().sum())
        cand_starts_mask = merged["cand"].notna() & (
            merged["anchor"].isna() | (merged["cand"] > merged["anchor"])
        )
        info = group.iloc[0]
        rows.append(
            {
                "player_id": pid,
                "player_display_name": info["player_display_name"],
                "position": info["position"],
                "team": info["team"],
                "platoon_points_added": best_total - anchor_total,
                "bye_covered": bool(anchor_bye & set(cand_weeks.index)),
                "weeks_candidate_starts": int(cand_starts_mask.sum()),
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values("platoon_points_added", ascending=False)
        .reset_index(drop=True)
    )


def platoon_grid(
    weekly_df: pd.DataFrame,
    anchor_player_id: str,
    candidate_player_id: str,
) -> pd.DataFrame:
    """Week-by-week matchup grid for anchor vs one candidate.

    Returns weeks 1..18 with anchor/candidate opponent, week_projection, and
    which player would start (higher projection, or the one not on bye).
    """
    def _for(pid: str) -> pd.DataFrame:
        return (
            weekly_df[weekly_df["player_id"] == pid]
            .drop_duplicates("week")
            .set_index("week")[["opponent", "week_projection"]]
        )

    anchor = _for(anchor_player_id).rename(
        columns={"opponent": "anchor_opp", "week_projection": "anchor_proj"}
    )
    cand = _for(candidate_player_id).rename(
        columns={"opponent": "cand_opp", "week_projection": "cand_proj"}
    )
    grid = pd.concat([anchor, cand], axis=1).sort_index()
    grid.index.name = "week"

    def _starter(row):
        a, c = row["anchor_proj"], row["cand_proj"]
        if pd.isna(a) and pd.isna(c):
            return "—"
        if pd.isna(a):
            return "cand"
        if pd.isna(c):
            return "anchor"
        return "cand" if c > a else "anchor"

    grid["starter"] = grid.apply(_starter, axis=1)
    return grid.reset_index()
