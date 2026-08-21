from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ScoringRules:
    name: str
    weights: dict[str, float]


STANDARD = ScoringRules(
    name="standard",
    weights={
        "passing_yards": 0.04,
        "passing_tds": 4.0,
        "passing_interceptions": -2.0,
        "passing_2pt_conversions": 2.0,
        "rushing_yards": 0.1,
        "rushing_tds": 6.0,
        "rushing_2pt_conversions": 2.0,
        "receiving_yards": 0.1,
        "receiving_tds": 6.0,
        "receiving_2pt_conversions": 2.0,
        "sack_fumbles_lost": -2.0,
        "rushing_fumbles_lost": -2.0,
        "receiving_fumbles_lost": -2.0,
        "fumble_recovery_tds": 6.0,
        "special_teams_tds": 6.0,
        # Kicker (ESPN standard: 3pt <40yd, 4pt 40-49, 5pt 50+; 1 PAT; -1 missed).
        "fg_made_0_19": 3.0,
        "fg_made_20_29": 3.0,
        "fg_made_30_39": 3.0,
        "fg_made_40_49": 4.0,
        "fg_made_50_59": 5.0,
        "fg_made_60_": 5.0,
        "fg_missed": -1.0,
        "pat_made": 1.0,
        "pat_missed": -1.0,
    },
)

HALF_PPR = ScoringRules(
    name="half_ppr",
    weights={**STANDARD.weights, "receptions": 0.5},
)

PPR = ScoringRules(
    name="ppr",
    weights={**STANDARD.weights, "receptions": 1.0},
)

RULESETS: dict[str, ScoringRules] = {
    STANDARD.name: STANDARD,
    HALF_PPR.name: HALF_PPR,
    PPR.name: PPR,
}


def compute_fantasy_points(df: pd.DataFrame, rules: ScoringRules) -> pd.Series:
    points = pd.Series(0.0, index=df.index)
    for col, weight in rules.weights.items():
        if col in df.columns:
            points = points + df[col].fillna(0) * weight
    return points


def score_weekly(df: pd.DataFrame, rules: ScoringRules) -> pd.DataFrame:
    out = df.copy()
    out["fantasy_points_ffs"] = compute_fantasy_points(df, rules)
    return out
