from __future__ import annotations

import re

import pandas as pd

from ffs.draft import FLEX_ELIGIBILITY

DEFAULT_LINEUP: dict[str, int] = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DST": 1}


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9\s]", "", name.lower()).strip()


def resolve_roster(
    projections: pd.DataFrame, names: list[str]
) -> tuple[pd.DataFrame, list[str]]:
    """Match roster names to projection rows. Returns (matched_df, unmatched_list)."""
    lookup = projections.assign(
        _norm=projections["player_display_name"].map(_normalize)
    )
    matched_rows: list[pd.Series] = []
    unmatched: list[str] = []
    for name in names:
        n = _normalize(name)
        exact = lookup[lookup["_norm"] == n]
        if len(exact) == 1:
            matched_rows.append(exact.iloc[0])
            continue
        subs = lookup[lookup["_norm"].str.contains(n, regex=False, na=False)]
        if len(subs) == 1:
            matched_rows.append(subs.iloc[0])
        elif len(subs) > 1:
            candidates = ", ".join(subs["player_display_name"].tolist())
            unmatched.append(f"{name} (ambiguous: {candidates})")
        else:
            unmatched.append(name)
    if not matched_rows:
        return projections.iloc[0:0].copy(), unmatched
    matched = pd.DataFrame(matched_rows).drop(columns="_norm", errors="ignore")
    return matched.reset_index(drop=True), unmatched


def optimize_lineup(
    roster_projections: pd.DataFrame,
    slots: dict[str, int] = DEFAULT_LINEUP,
    flex_eligibility: dict[str, tuple[str, ...]] = FLEX_ELIGIBILITY,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (starters, bench). Starters gains a `slot` column.

    Fills position-locked slots first, then flex slots in order of increasing
    eligibility (most restrictive first) so SUPER_FLEX doesn't steal a QB from
    a dedicated WRRB_FLEX pool, etc.
    """
    available = roster_projections.sort_values("projection", ascending=False).copy()
    used_ids: set = set()
    starter_rows: list[dict] = []

    for slot_name, n in slots.items():
        if slot_name in flex_eligibility:
            continue
        pool = available[
            (available["position"] == slot_name) & (~available["player_id"].isin(used_ids))
        ].head(n)
        for _, row in pool.iterrows():
            r = row.to_dict()
            r["slot"] = slot_name
            starter_rows.append(r)
            used_ids.add(row["player_id"])

    flex_slots = [(name, n) for name, n in slots.items() if name in flex_eligibility]
    flex_slots.sort(key=lambda x: len(flex_eligibility[x[0]]))
    for slot_name, n in flex_slots:
        eligible = flex_eligibility[slot_name]
        pool = available[
            available["position"].isin(eligible)
            & (~available["player_id"].isin(used_ids))
        ].head(n)
        for _, row in pool.iterrows():
            r = row.to_dict()
            r["slot"] = slot_name
            starter_rows.append(r)
            used_ids.add(row["player_id"])

    starters = pd.DataFrame(starter_rows)
    bench = (
        available[~available["player_id"].isin(used_ids)]
        .sort_values("projection", ascending=False)
        .reset_index(drop=True)
    )
    return starters, bench
