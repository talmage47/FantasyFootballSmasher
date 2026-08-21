from __future__ import annotations

import pandas as pd

TEAM_NICKNAMES: dict[str, str] = {
    "ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills",
    "CAR": "Panthers", "CHI": "Bears", "CIN": "Bengals", "CLE": "Browns",
    "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers",
    "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "KC": "Chiefs",
    "LA": "Rams", "LAC": "Chargers", "LV": "Raiders", "MIA": "Dolphins",
    "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants",
    "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SEA": "Seahawks",
    "SF": "49ers", "TB": "Buccaneers", "TEN": "Titans", "WAS": "Commanders",
}

STANDARD_DST_WEIGHTS: dict[str, float] = {
    "def_sacks": 1.0,
    "def_interceptions": 2.0,
    "fumble_recovery_opp": 2.0,
    "def_tds": 6.0,
    "def_safeties": 2.0,
    "fg_blocked": 2.0,
    "pt_blocked": 2.0,
    "special_teams_tds": 6.0,
}

STANDARD_POINTS_ALLOWED_BUCKETS: list[tuple[int, float, float]] = [
    # (upper_bound_inclusive, points). Ordered low to high.
    (0, 10.0),
    (6, 7.0),
    (13, 4.0),
    (17, 1.0),
    (27, 0.0),
    (34, -1.0),
    (45, -4.0),
    (10_000, -5.0),
]


def _points_allowed_bonus(
    points_allowed: float,
    buckets: list[tuple[int, float]] = STANDARD_POINTS_ALLOWED_BUCKETS,
) -> float:
    for upper, bonus in buckets:
        if points_allowed <= upper:
            return bonus
    return 0.0


# Sleeper defensive scoring_settings key → per-team-stats column.
_SLEEPER_DST_KEYS: dict[str, str] = {
    "sack": "def_sacks",
    "int": "def_interceptions",
    "fum_rec": "fumble_recovery_opp",
    "def_td": "def_tds",
    "safe": "def_safeties",
    "ff": "def_fumbles_forced",
}

# (upper points-allowed bound inclusive, Sleeper key)
_SLEEPER_PA_BRACKETS: list[tuple[int, str]] = [
    (0, "pts_allow_0"),
    (6, "pts_allow_1_6"),
    (13, "pts_allow_7_13"),
    (20, "pts_allow_14_20"),
    (27, "pts_allow_21_27"),
    (34, "pts_allow_28_34"),
    (10_000, "pts_allow_35p"),
]


def parse_sleeper_dst(
    settings: dict,
) -> tuple[dict[str, float], list[tuple[int, float]]]:
    """Translate Sleeper's scoring_settings into (weights, points_allowed_buckets)."""
    weights: dict[str, float] = {}
    for sk, nc in _SLEEPER_DST_KEYS.items():
        v = settings.get(sk)
        if v:
            weights[nc] = float(v)
    blk = settings.get("blk_kick")
    if blk:
        weights["fg_blocked"] = float(blk)
        weights["pt_blocked"] = float(blk)
    st_td = settings.get("def_st_td") or settings.get("st_td")
    if st_td:
        weights["special_teams_tds"] = float(st_td)
    buckets: list[tuple[int, float]] = [
        (upper, float(settings.get(sk) or 0.0)) for upper, sk in _SLEEPER_PA_BRACKETS
    ]
    return weights, buckets


def _points_allowed_from_schedule(schedule: pd.DataFrame) -> pd.DataFrame:
    """One row per (season, week, team) with the points its DST allowed."""
    home = schedule[["season", "week", "home_team", "away_score"]].rename(
        columns={"home_team": "team", "away_score": "points_allowed"}
    )
    away = schedule[["season", "week", "away_team", "home_score"]].rename(
        columns={"away_team": "team", "home_score": "points_allowed"}
    )
    return pd.concat([home, away], ignore_index=True)


def score_dst(
    team_stats: pd.DataFrame,
    schedule: pd.DataFrame,
    weights: dict[str, float] = STANDARD_DST_WEIGHTS,
    points_allowed_buckets: list[tuple[int, float]] = STANDARD_POINTS_ALLOWED_BUCKETS,
) -> pd.DataFrame:
    """Compute per-team-per-week DST fantasy points.

    Returns a frame with the columns the rest of the pipeline expects on scored
    weekly data — `player_id`, `player_display_name`, `position`, `season`,
    `week`, `team`, `opponent_team`, `fantasy_points_ffs`, `season_type` — so
    it can be concatenated onto the player-level scored table.
    """
    ts = team_stats.copy()
    base = pd.Series(0.0, index=ts.index)
    for col, weight in weights.items():
        if col in ts.columns:
            base = base + ts[col].fillna(0) * weight

    pa = _points_allowed_from_schedule(schedule)
    merged = ts.merge(pa, on=["season", "week", "team"], how="left")
    merged["points_allowed"] = merged["points_allowed"].fillna(0)
    bonus = merged["points_allowed"].map(
        lambda x: _points_allowed_bonus(x, points_allowed_buckets)
    )
    merged["fantasy_points_ffs"] = base.values + bonus.values

    merged["position"] = "DST"
    merged["player_id"] = "DST-" + merged["team"].astype(str)
    merged["player_display_name"] = (
        merged["team"].map(TEAM_NICKNAMES).fillna(merged["team"]) + " DST"
    )
    return merged[[
        "player_id", "player_display_name", "position",
        "season", "week", "season_type",
        "team", "opponent_team",
        "points_allowed", "fantasy_points_ffs",
    ]]
