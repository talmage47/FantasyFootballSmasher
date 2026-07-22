from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_STARTERS: dict[str, int] = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}
DEFAULT_FLEX_POSITIONS: tuple[str, ...] = ("RB", "WR", "TE")
DEFAULT_FLEX_STARTERS: int = 1
ROOKIE_POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE")


def replacement_ranks(
    teams: int,
    starters: dict[str, int] = DEFAULT_STARTERS,
    flex_positions: tuple[str, ...] = DEFAULT_FLEX_POSITIONS,
    flex_starters: int = DEFAULT_FLEX_STARTERS,
) -> dict[str, int]:
    """Nth-ranked player per position who represents replacement level."""
    ranks: dict[str, int] = {}
    flex_share = teams * flex_starters / len(flex_positions)
    for pos, n_starters in starters.items():
        base = n_starters * teams
        if pos in flex_positions:
            base += round(flex_share)
        ranks[pos] = int(base)
    return ranks


def draft_rankings(
    season_projections: pd.DataFrame,
    teams: int = 12,
    starters: dict[str, int] = DEFAULT_STARTERS,
    flex_positions: tuple[str, ...] = DEFAULT_FLEX_POSITIONS,
    flex_starters: int = DEFAULT_FLEX_STARTERS,
) -> pd.DataFrame:
    """Value-based draft rankings across positions."""
    ranks = replacement_ranks(teams, starters, flex_positions, flex_starters)
    frames = []
    for pos, replacement_rank in ranks.items():
        pos_df = (
            season_projections[season_projections["position"] == pos]
            .sort_values("projected_points", ascending=False)
            .reset_index(drop=True)
        )
        if pos_df.empty:
            continue
        pos_df["pos_rank"] = pos_df.index + 1
        if len(pos_df) >= replacement_rank:
            replacement_pts = pos_df.iloc[replacement_rank - 1]["projected_points"]
        else:
            replacement_pts = pos_df["projected_points"].min()
        pos_df["vbd"] = pos_df["projected_points"] - replacement_pts
        pos_df["replacement_pts"] = replacement_pts
        frames.append(pos_df)

    ranked = (
        pd.concat(frames, ignore_index=True)
        .sort_values("vbd", ascending=False)
        .reset_index(drop=True)
    )
    ranked["overall_rank"] = ranked.index + 1
    return ranked


def with_adp(rankings: pd.DataFrame, adp: pd.DataFrame) -> pd.DataFrame:
    """Attach market ADP and compute adp_delta (positive = market drafts later than we do)."""
    adp_slim = (
        adp.dropna(subset=["player_id"])[["player_id", "adp", "sd", "best", "worst"]]
        .drop_duplicates("player_id")
    )
    merged = rankings.merge(adp_slim, on="player_id", how="left")
    merged["adp_delta"] = merged["adp"] - merged["overall_rank"]
    return merged


def with_rookies(
    rankings: pd.DataFrame,
    adp: pd.DataFrame,
    positions: tuple[str, ...] = ROOKIE_POSITIONS,
) -> pd.DataFrame:
    """Add ADP entries with no `player_id` (typically rookies) using market-implied projections.

    Rookies have no NFL games, so the model can't produce a baseline. We approximate
    their projected points by interpolating between same-position, matched (veteran)
    players on the (adp, projected_points) curve — i.e. "the market is drafting this
    rookie roughly here, so treat him like other players drafted at that ADP".

    Assumes `rankings` already has `adp` (from `with_adp`) and `replacement_pts`
    (from `draft_rankings`). Recomputes `overall_rank`, `pos_rank`, and `adp_delta`
    after insertion so rookies interleave correctly.
    """
    rookies_raw = adp[adp["player_id"].isna() & adp["pos"].isin(positions)]
    if rookies_raw.empty:
        rankings = rankings.copy()
        rankings["is_rookie"] = False
        return rankings

    replacement = rankings.dropna(subset=["replacement_pts"]).groupby("position")[
        "replacement_pts"
    ].first().to_dict()

    rookie_frames = []
    for pos in positions:
        pos_matched = (
            rankings[(rankings["position"] == pos) & rankings["adp"].notna()]
            .sort_values("adp")
        )
        if pos_matched.empty:
            continue
        pos_rookies = rookies_raw[rookies_raw["pos"] == pos].copy()
        if pos_rookies.empty:
            continue
        replacement_pts = replacement.get(pos, pos_matched["projected_points"].min())
        pos_rookies["projected_points"] = np.interp(
            pos_rookies["adp"].to_numpy(dtype=float),
            pos_matched["adp"].to_numpy(dtype=float),
            pos_matched["projected_points"].to_numpy(dtype=float),
            right=replacement_pts,
        )
        rookie_frames.append(pos_rookies)

    rankings = rankings.copy()
    rankings["is_rookie"] = False
    if not rookie_frames:
        return rankings

    rookies = pd.concat(rookie_frames, ignore_index=True).rename(
        columns={"player": "player_display_name", "pos": "position"}
    )
    rookies["is_rookie"] = True
    rookies["replacement_pts"] = rookies["position"].map(replacement)
    rookies["vbd"] = rookies["projected_points"] - rookies["replacement_pts"]

    combined = pd.concat([rankings, rookies], ignore_index=True, sort=False)
    combined = combined.sort_values("vbd", ascending=False).reset_index(drop=True)
    combined["overall_rank"] = combined.index + 1
    combined["pos_rank"] = (
        combined.groupby("position")["projected_points"]
        .rank(ascending=False, method="min")
        .astype(int)
    )
    combined["adp_delta"] = combined["adp"] - combined["overall_rank"]
    return combined
