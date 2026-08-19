from __future__ import annotations

import pandas as pd

from ffs import draft as draft_mod

DISPLAY_POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE", "K", "DST")
K_DST_UNLOCK_ROUND: int = 8
LATE_ROUND_POSITIONS: frozenset[str] = frozenset({"K", "DST"})


def snake_picks(slot: int, teams: int, rounds: int) -> list[int]:
    """1-indexed pick numbers for a slot across a snake draft."""
    picks: list[int] = []
    for r in range(1, rounds + 1):
        offset = slot if r % 2 == 1 else teams - slot + 1
        picks.append((r - 1) * teams + offset)
    return picks


def current_round(pick_no: int, teams: int) -> int:
    return ((pick_no - 1) // teams) + 1


def slot_on_the_clock(pick_no: int, teams: int) -> int:
    r = current_round(pick_no, teams)
    idx = (pick_no - 1) % teams
    return (idx + 1) if r % 2 == 1 else (teams - idx)


def next_own_pick(
    current_pick_no: int, my_slot: int, teams: int, total_rounds: int
) -> int | None:
    """Next pick number strictly >= current_pick_no belonging to my_slot, or None."""
    for p in snake_picks(my_slot, teams, total_rounds):
        if p >= current_pick_no:
            return p
    return None


def positional_need(
    roster_positions: list[str],
    starters: dict[str, int],
    flex_counts: dict[str, int],
    flex_eligibility: dict[str, tuple[str, ...]] = draft_mod.FLEX_ELIGIBILITY,
) -> dict[str, float]:
    """Per-position urgency multiplier for future picks.

    1.0  → still need a starter
    0.5–0.8 → starter filled but flex-eligible or reasonable bench depth
    0.2  → oversaturated
    """
    counts: dict[str, int] = {}
    for p in roster_positions:
        counts[p] = counts.get(p, 0) + 1
    need: dict[str, float] = {}
    for pos in DISPLAY_POSITIONS:
        required = starters.get(pos, 0)
        have = counts.get(pos, 0)
        if have < required:
            need[pos] = 1.0
            continue
        flex_share = _flex_capacity_share(pos, flex_counts, flex_eligibility)
        # 1 bench body still useful — inflate if flex-eligible
        if have <= required + 1:
            need[pos] = 0.5 + 0.3 * flex_share
        else:
            need[pos] = 0.2 + 0.2 * flex_share
    return need


def _flex_capacity_share(
    pos: str, flex_counts: dict[str, int], flex_eligibility: dict[str, tuple[str, ...]]
) -> float:
    return float(
        any(pos in flex_eligibility.get(name, ()) and n > 0 for name, n in flex_counts.items())
    )


def remaining_starter_slots(
    roster_positions: list[str],
    starters: dict[str, int],
    flex_counts: dict[str, int],
) -> dict[str, int]:
    """Report per-slot shortfall (starter positions only, plus a lump for flex)."""
    counts: dict[str, int] = {}
    for p in roster_positions:
        counts[p] = counts.get(p, 0) + 1
    out: dict[str, int] = {}
    for pos, required in starters.items():
        short = required - counts.get(pos, 0)
        if short > 0:
            out[pos] = short
    for slot_name, count in flex_counts.items():
        if count > 0:
            out[slot_name] = count  # flex is always a slot to fill; hard to know count
    return out


def wait_cost_by_position(
    board: pd.DataFrame,
    drafted_ids: set[str],
    next_pick_no: int | None,
) -> dict[str, float]:
    """Per-position VBD lost by waiting until your next pick.

    Uses ADP as the sniping proxy: `best available at position whose ADP > next_pick_no`
    is treated as the fallback. Difference from the current top-available at that
    position is the wait cost. Positions with no `adp` column produce 0.
    """
    if next_pick_no is None or "adp" not in board.columns:
        return {}
    available = board[~board["player_id"].isin(drafted_ids)]
    out: dict[str, float] = {}
    for pos, group in available.groupby("position", dropna=False):
        sorted_group = group.sort_values("vbd", ascending=False)
        if sorted_group.empty:
            continue
        top_vbd = float(sorted_group.iloc[0]["vbd"])
        surviving = sorted_group[
            sorted_group["adp"].notna() & (sorted_group["adp"] > next_pick_no)
        ]
        fallback_vbd = float(surviving.iloc[0]["vbd"]) if not surviving.empty else 0.0
        out[pos] = top_vbd - fallback_vbd
    return out


def score_candidates(
    board: pd.DataFrame,
    drafted_ids: set[str],
    need_mult: dict[str, float],
    wait_cost: dict[str, float],
    lock_out_positions: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Attach fit_score to the available board and sort descending.

    fit_score = vbd × need_mult + 0.5 × wait_cost × need_mult
    A big wait_cost at a position you don't need is discounted; conversely a modest
    wait_cost at a position you desperately need still surfaces above pure VBD.
    """
    available = board[~board["player_id"].isin(drafted_ids)].copy()
    if lock_out_positions:
        available = available[~available["position"].isin(lock_out_positions)]
    if available.empty:
        return available
    available["need_mult"] = available["position"].map(lambda p: need_mult.get(p, 0.5))
    available["wait_cost"] = available["position"].map(lambda p: wait_cost.get(p, 0.0))
    available["fit_score"] = (
        available["vbd"].fillna(0.0) * available["need_mult"]
        + 0.5 * available["wait_cost"] * available["need_mult"]
    )
    return available.sort_values("fit_score", ascending=False).reset_index(drop=True)


def top_per_position(
    scored: pd.DataFrame,
    board: pd.DataFrame,
    drafted_ids: set[str],
    wait_cost: dict[str, float],
    positions: tuple[str, ...] = DISPLAY_POSITIONS,
) -> pd.DataFrame:
    """Best remaining player at each position — always shown regardless of need multipliers.

    Sourced from the raw board (not the scored/lock-out board) so K/DST always
    appear even before their unlock round.
    """
    available = board[~board["player_id"].isin(drafted_ids)]
    rows = []
    for pos in positions:
        pos_rows = available[available["position"] == pos].sort_values("vbd", ascending=False)
        if pos_rows.empty:
            continue
        r = pos_rows.iloc[0].to_dict()
        r["wait_cost"] = wait_cost.get(pos, 0.0)
        rows.append(r)
    return pd.DataFrame(rows)


def favorite_team_pick(
    board: pd.DataFrame, drafted_ids: set[str], team: str
) -> pd.Series | None:
    """Best available player on `team` (case-insensitive)."""
    available = board[~board["player_id"].isin(drafted_ids)]
    team_rows = available[available["team"].fillna("").str.upper() == team.upper()]
    if team_rows.empty:
        return None
    return team_rows.sort_values("vbd", ascending=False).iloc[0]


def explain_candidate(
    row: pd.Series,
    starters: dict[str, int],
    roster_positions: list[str],
    anchors_bye: dict[str, int],
    next_pick_no: int | None,
) -> str:
    """One-line rationale built from the row's numeric features."""
    parts: list[str] = []
    pos = row.get("position")
    counts: dict[str, int] = {}
    for p in roster_positions:
        counts[p] = counts.get(p, 0) + 1
    required = starters.get(pos, 0)
    have = counts.get(pos, 0)
    if pos in ("QB", "RB", "WR", "TE") and have < required:
        parts.append(f"fills {pos} starter need")
    wc = float(row.get("wait_cost") or 0.0)
    if wc >= 25:
        parts.append(f"tier cliff (−{wc:.0f} VBD if you wait)")
    elif wc <= 3 and next_pick_no is not None:
        parts.append(f"safe wait — {pos} pool deep")
    bye = row.get("bye_week")
    if pd.notna(bye):
        bye_i = int(bye)
        conflicts = sum(1 for _, b in anchors_bye.items() if b == bye_i)
        if conflicts >= 2:
            parts.append(f"W{bye_i} bye stacks {conflicts} starters")
        elif conflicts == 0 and anchors_bye:
            parts.append(f"clean W{bye_i} bye")
    adp_delta = row.get("adp_delta")
    if pd.notna(adp_delta):
        if adp_delta >= 8:
            parts.append(f"ADP value +{int(adp_delta)}")
        elif adp_delta <= -8:
            parts.append(f"reach {int(adp_delta)} vs ADP")
    injury = row.get("injury_status")
    if injury in ("Out", "Doubtful", "Questionable"):
        parts.append(str(injury))
    if bool(row.get("injury_prone")):
        pct = float(row.get("games_missed_pct") or 0)
        parts.append(f"injury-prone (missed {pct * 100:.0f}%)")
    if not parts:
        parts.append("best available at this VBD")
    return "; ".join(parts)


def build_drafted_set(picks: list[dict], player_id_map: dict[str, str]) -> set[str]:
    """Translate Sleeper pick rows to a set of gsis_ids that appear on our board.

    `player_id_map` maps Sleeper player_id → gsis_id (usually via the cached
    Sleeper players.json). DSTs are keyed by team abbreviation in Sleeper; those
    are passed through and matched by a downstream helper.
    """
    ids: set[str] = set()
    for p in picks:
        pid = p.get("player_id")
        if pid is None:
            continue
        mapped = player_id_map.get(pid, pid)
        if mapped:
            ids.add(mapped)
    return ids
