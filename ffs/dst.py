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


def _points_allowed_bonus(points_allowed: float) -> float:
    for upper, bonus in STANDARD_POINTS_ALLOWED_BUCKETS:
        if points_allowed <= upper:
            return bonus
    return 0.0


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
    bonus = merged["points_allowed"].map(_points_allowed_bonus)
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
