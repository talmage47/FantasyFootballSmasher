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


# Sleeper's scoring_settings key → nflreadpy weekly stats column.
# Only 1:1 mappings live here; fumbles-lost and blocked-kicks apply to
# multiple underlying columns and are handled specially in parse_sleeper_scoring.
_SLEEPER_PLAYER_KEYS: dict[str, str] = {
    "pass_yd": "passing_yards",
    "pass_td": "passing_tds",
    "pass_int": "passing_interceptions",
    "pass_2pt": "passing_2pt_conversions",
    "rush_yd": "rushing_yards",
    "rush_td": "rushing_tds",
    "rush_2pt": "rushing_2pt_conversions",
    "rec": "receptions",
    "rec_yd": "receiving_yards",
    "rec_td": "receiving_tds",
    "rec_2pt": "receiving_2pt_conversions",
    "fum_rec_td": "fumble_recovery_tds",
    "fgm_0_19": "fg_made_0_19",
    "fgm_20_29": "fg_made_20_29",
    "fgm_30_39": "fg_made_30_39",
    "fgm_40_49": "fg_made_40_49",
    "fgm_50_59": "fg_made_50_59",
    "fgm_60p": "fg_made_60_",
    "fgmiss": "fg_missed",
    "xpm": "pat_made",
    "xpmiss": "pat_missed",
    "st_td": "special_teams_tds",
}

_FUMBLE_LOST_COLS: tuple[str, ...] = (
    "sack_fumbles_lost",
    "rushing_fumbles_lost",
    "receiving_fumbles_lost",
)


def sleeper_ruleset_name(league_id: str) -> str:
    return f"sleeper_{league_id}"


def parse_sleeper_scoring(settings: dict, league_id: str) -> ScoringRules:
    """Translate a Sleeper league's scoring_settings dict into a ScoringRules.

    Zero-valued keys are omitted so we don't churn through a hundred no-op
    multiplications per row. `fum_lost` is broadcast to every nflreadpy
    *_fumbles_lost column because Sleeper applies it once per lost fumble
    regardless of source.
    """
    weights: dict[str, float] = {}
    for sleeper_key, nfl_col in _SLEEPER_PLAYER_KEYS.items():
        v = settings.get(sleeper_key)
        if v:
            weights[nfl_col] = float(v)
    fum_lost = settings.get("fum_lost")
    if fum_lost:
        for col in _FUMBLE_LOST_COLS:
            weights[col] = float(fum_lost)
    return ScoringRules(name=sleeper_ruleset_name(league_id), weights=weights)
