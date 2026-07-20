from __future__ import annotations

import pandas as pd

DEFAULT_STARTERS: dict[str, int] = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}
DEFAULT_FLEX_POSITIONS: tuple[str, ...] = ("RB", "WR", "TE")
DEFAULT_FLEX_STARTERS: int = 1


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
