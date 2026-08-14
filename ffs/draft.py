from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd

DEFAULT_STARTERS: dict[str, int] = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DST": 1}
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


def _normalize_name(s: object) -> str:
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s)
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def with_ffc_adp(rankings: pd.DataFrame, ffc: pd.DataFrame) -> pd.DataFrame:
    """Attach Fantasy Football Calculator ADP as `ffc_adp` and `ffc_delta`.

    FFC shares no player_id with nflreadpy. Non-DST rows join by normalized
    player name; DST rows join by team abbreviation (FFC labels DSTs as
    "Denver Defense" with the team code in the `team` field).
    """
    out = rankings.copy()
    out["ffc_adp"] = pd.NA
    out["ffc_stdev"] = pd.NA
    out["ffc_n"] = pd.NA

    if ffc.empty:
        out["ffc_delta"] = pd.NA
        return out

    ffc = ffc.copy()
    players = ffc[ffc["position"] != "DEF"].copy()
    players["_key"] = players["name"].map(_normalize_name)
    players = players.drop_duplicates("_key")[
        ["_key", "adp", "stdev", "times_drafted"]
    ].rename(columns={"adp": "ffc_adp", "stdev": "ffc_stdev", "times_drafted": "ffc_n"})

    out["_key"] = out["player_display_name"].map(_normalize_name)
    lookup = players.set_index("_key")
    for col in ("ffc_adp", "ffc_stdev", "ffc_n"):
        mapped = out["_key"].map(lookup[col])
        out[col] = out[col].where(mapped.isna(), mapped)

    dsts = ffc[ffc["position"] == "DEF"].drop_duplicates("team")
    dst_lookup = dsts.set_index("team")
    dst_mask = out["position"] == "DST"
    if dst_mask.any():
        for col, src in (("ffc_adp", "adp"), ("ffc_stdev", "stdev"), ("ffc_n", "times_drafted")):
            mapped = out.loc[dst_mask, "team"].map(dst_lookup[src])
            out.loc[dst_mask, col] = mapped

    out = out.drop(columns=["_key"])
    out["ffc_delta"] = out["ffc_adp"] - out["overall_rank"]
    return out


def with_hybrid_replacement(
    rankings: pd.DataFrame,
    teams: int = 12,
) -> pd.DataFrame:
    """Recompute VBD using max(current replacement_pts, market-implied replacement).

    The market-implied replacement is the median projection among players the
    market has actually drafted at this position (ADP within the drafted pool
    of `teams * 15` picks). Where the market's median projection is higher
    than our VBD replacement, we adopt the market's — that dampens inflated
    VBD when our top-end projections outrun the market. For positions where
    the market and our replacement roughly agree (QB/RB/WR at 12 teams), the
    max is our VBD replacement and nothing changes.

    Assumes `rankings` already carries `adp` from with_adp. Recomputes
    overall_rank, pos_rank, and adp_delta after.
    """
    out = rankings.copy()
    if "adp" not in out.columns:
        return out  # no market data; nothing to hybridize

    drafted_cutoff = teams * 15  # 15 rounds ≈ standard roster depth
    for pos in out["position"].dropna().unique():
        pos_mask = out["position"] == pos
        pos_df = out[pos_mask]
        drafted = pos_df.dropna(subset=["adp"]).loc[
            lambda d: d["adp"] <= drafted_cutoff
        ]
        if drafted.empty:
            continue
        market_replacement = drafted["projected_points"].median()
        current_replacement = pos_df["replacement_pts"].iloc[0]
        new_replacement = max(current_replacement, market_replacement)
        if new_replacement > current_replacement:
            out.loc[pos_mask, "replacement_pts"] = new_replacement
            out.loc[pos_mask, "vbd"] = (
                out.loc[pos_mask, "projected_points"] - new_replacement
            )

    out = out.sort_values("vbd", ascending=False).reset_index(drop=True)
    out["overall_rank"] = out.index + 1
    if "adp" in out.columns:
        out["adp_delta"] = out["adp"] - out["overall_rank"]
    if "ffc_adp" in out.columns:
        out["ffc_delta"] = out["ffc_adp"] - out["overall_rank"]
    return out


def with_rookies(
    rankings: pd.DataFrame,
    adp: pd.DataFrame,
    ffc: pd.DataFrame | None = None,
    positions: tuple[str, ...] = ROOKIE_POSITIONS,
) -> pd.DataFrame:
    """Add ADP entries with no `player_id` (typically rookies) using market-implied projections.

    Rookies have no NFL games, so the model can't produce a baseline. We approximate
    their projected points by interpolating between same-position, matched (veteran)
    players on the (adp, projected_points) curve — i.e. "the market is drafting this
    rookie roughly here, so treat him like other players drafted at that ADP".

    When `ffc` is provided, prefer FFC ADP over FantasyPros for both the
    interpolation curve x-axis and the rookie's placement — FFC reflects real
    mock drafts and is meaningfully more accurate than FP ECR for rookies (see
    project_model_issues.md: Jeanty was 30+ picks underrated by FP-based interp).

    Assumes `rankings` already has `adp` (from `with_adp`) and `replacement_pts`
    (from `draft_rankings`). Recomputes `overall_rank`, `pos_rank`, `adp_delta`,
    and `ffc_delta` after insertion so rookies interleave correctly.
    """
    rookies_raw = adp[adp["player_id"].isna() & adp["pos"].isin(positions)]
    if rookies_raw.empty:
        rankings = rankings.copy()
        rankings["is_rookie"] = False
        return rankings

    ffc_by_key: dict[str, float] = {}
    if ffc is not None and not ffc.empty:
        ffc_players = ffc[ffc["position"] != "DEF"].copy()
        ffc_players["_key"] = ffc_players["name"].map(_normalize_name)
        ffc_by_key = (
            ffc_players.drop_duplicates("_key").set_index("_key")["adp"].to_dict()
        )

    have_ffc_col = "ffc_adp" in rankings.columns

    replacement = rankings.dropna(subset=["replacement_pts"]).groupby("position")[
        "replacement_pts"
    ].first().to_dict()

    rookie_frames = []
    for pos in positions:
        pos_all = rankings[rankings["position"] == pos]
        fp_curve = pos_all.dropna(subset=["adp"]).sort_values("adp")
        if fp_curve.empty:
            continue
        ffc_curve = (
            pos_all.dropna(subset=["ffc_adp"]).sort_values("ffc_adp")
            if have_ffc_col else pos_all.iloc[0:0]
        )
        replacement_pts = replacement.get(pos, fp_curve["projected_points"].min())

        pos_rookies = rookies_raw[rookies_raw["pos"] == pos].copy()
        if pos_rookies.empty:
            continue

        pos_rookies["ffc_adp"] = pos_rookies["player"].map(
            lambda n: ffc_by_key.get(_normalize_name(n))
        )

        proj = np.empty(len(pos_rookies))
        for i, (_, row) in enumerate(pos_rookies.iterrows()):
            if not ffc_curve.empty and pd.notna(row["ffc_adp"]):
                proj[i] = np.interp(
                    row["ffc_adp"],
                    ffc_curve["ffc_adp"].to_numpy(dtype=float),
                    ffc_curve["projected_points"].to_numpy(dtype=float),
                    right=replacement_pts,
                )
            else:
                proj[i] = np.interp(
                    row["adp"],
                    fp_curve["adp"].to_numpy(dtype=float),
                    fp_curve["projected_points"].to_numpy(dtype=float),
                    right=replacement_pts,
                )
        pos_rookies["projected_points"] = proj
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
    if "ffc_adp" in combined.columns:
        combined["ffc_delta"] = combined["ffc_adp"] - combined["overall_rank"]
    return combined


def with_tiers(
    rankings: pd.DataFrame,
    teams: int = 12,
    starters: dict[str, int] = DEFAULT_STARTERS,
    flex_positions: tuple[str, ...] = DEFAULT_FLEX_POSITIONS,
    flex_starters: int = DEFAULT_FLEX_STARTERS,
    gap_multiplier: float = 1.5,
) -> pd.DataFrame:
    """Add a `tier` column: consecutive players at a position, split on unusually large VBD gaps.

    Within each position, sort by VBD descending, compute gap[i] = vbd[i] - vbd[i+1],
    and start a new tier whenever gap[i] > gap_multiplier * median(gap) for that position.
    The median is taken over the top 2× replacement-rank players so deep-bench noise
    doesn't dominate. Tiers are numbered 1..N within each position.
    """
    ranks = replacement_ranks(teams, starters, flex_positions, flex_starters)
    out = rankings.copy()
    out["tier"] = pd.NA

    for pos, replacement_rank in ranks.items():
        pos_mask = out["position"] == pos
        pos_df = out[pos_mask].sort_values("vbd", ascending=False)
        if pos_df.empty:
            continue
        vbd = pos_df["vbd"].to_numpy(dtype=float)
        gaps = vbd[:-1] - vbd[1:]
        window = min(len(gaps), max(replacement_rank * 2 - 1, 1))
        threshold = np.median(gaps[:window]) * gap_multiplier if window > 0 else 0.0
        tiers = np.ones(len(vbd), dtype=int)
        for i, gap in enumerate(gaps):
            tiers[i + 1] = tiers[i] + (1 if gap > threshold else 0)
        out.loc[pos_df.index, "tier"] = tiers

    out["tier"] = out["tier"].astype("Int64")
    return out
