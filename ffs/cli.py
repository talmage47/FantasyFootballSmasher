from __future__ import annotations

from typing import Annotated

import typer

from ffs import career as career_mod
from ffs import config, ingest, matchups, scoring

app = typer.Typer(help="Fantasy Football Smasher", no_args_is_help=True)


def _resolve_seasons(
    seasons: list[int] | None, start: int | None, end: int | None
) -> list[int]:
    picked: set[int] = set(seasons or [])
    if start is not None or end is not None:
        s = start if start is not None else min(config.DEFAULT_SEASONS)
        e = end if end is not None else max(config.DEFAULT_SEASONS)
        picked.update(range(s, e + 1))
    if not picked:
        picked.update(config.DEFAULT_SEASONS)
    return sorted(picked)


@app.command()
def fetch(
    seasons: Annotated[
        list[int] | None, typer.Option("--season", "-s", help="Specific season (repeatable)")
    ] = None,
    start: Annotated[int | None, typer.Option("--start", help="Inclusive start season")] = None,
    end: Annotated[int | None, typer.Option("--end", help="Inclusive end season")] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Refetch even if the Parquet already exists")
    ] = False,
) -> None:
    """Download weekly NFL player stats and save to Parquet."""
    for season in _resolve_seasons(seasons, start, end):
        path = config.weekly_raw_path(season)
        if path.exists() and not force:
            typer.echo(f"[skip] {season}: {path.name} already exists")
            continue
        typer.echo(f"Fetching weekly stats for {season}…")
        df = ingest.fetch_weekly(season)
        ingest.save_weekly(df, season)
        typer.echo(f"  → {len(df):,} rows saved to {path}")


@app.command("fetch-schedules")
def fetch_schedules_cmd(
    seasons: Annotated[list[int] | None, typer.Option("--season", "-s")] = None,
    start: Annotated[int | None, typer.Option("--start")] = None,
    end: Annotated[int | None, typer.Option("--end")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Download NFL schedules and save to Parquet."""
    for season in _resolve_seasons(seasons, start, end):
        path = config.schedules_path(season)
        if path.exists() and not force:
            typer.echo(f"[skip] {season}: {path.name} already exists")
            continue
        typer.echo(f"Fetching schedule for {season}…")
        df = ingest.fetch_schedules(season)
        ingest.save_schedules(df, season)
        typer.echo(f"  → {len(df):,} games saved to {path}")


@app.command()
def schedule(
    season: Annotated[int, typer.Option("--season", "-s")],
    week: Annotated[int | None, typer.Option("--week", "-w")] = None,
) -> None:
    """Print matchups for a season (optionally a single week)."""
    df = ingest.load_schedules(season)
    if week is not None:
        df = df[df["week"] == week]
    cols = [c for c in ("week", "gameday", "away_team", "home_team",
                        "away_score", "home_score", "spread_line", "total_line")
            if c in df.columns]
    typer.echo(df[cols].sort_values(["week", "gameday"]).to_string(index=False))


@app.command()
def score(
    seasons: Annotated[
        list[int] | None, typer.Option("--season", "-s", help="Specific season (repeatable)")
    ] = None,
    start: Annotated[int | None, typer.Option("--start")] = None,
    end: Annotated[int | None, typer.Option("--end")] = None,
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Compute fantasy points for the given seasons using the given ruleset."""
    if ruleset not in scoring.RULESETS:
        raise typer.BadParameter(f"unknown ruleset {ruleset!r}; known: {list(scoring.RULESETS)}")
    rules = scoring.RULESETS[ruleset]
    for season in _resolve_seasons(seasons, start, end):
        raw_path = config.weekly_raw_path(season)
        if not raw_path.exists():
            typer.echo(f"[skip] {season}: no raw file, run `ffs fetch --season {season}` first")
            continue
        out_path = config.weekly_scored_path(season, rules.name)
        if out_path.exists() and not force:
            typer.echo(f"[skip] {season}: {out_path.name} already scored")
            continue
        df = ingest.load_weekly(season)
        scored = scoring.score_weekly(df, rules)
        config.ensure_parent(out_path)
        scored.to_parquet(out_path, index=False)
        typer.echo(f"Scored {len(scored):,} rows for {season} → {out_path}")


@app.command()
def leaders(
    season: Annotated[int, typer.Option("--season", "-s")],
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
    position: Annotated[str | None, typer.Option("--position", "-p")] = None,
    top: Annotated[int, typer.Option("--top")] = 25,
) -> None:
    """Show top scorers for a single season."""
    df = career_mod.load_scored([season], ruleset=ruleset)
    if position:
        df = df[df["position"] == position.upper()]
    leaders_df = (
        df.groupby(["player_id", "player_display_name", "position"], dropna=False)[
            "fantasy_points_ffs"
        ]
        .sum()
        .reset_index()
        .sort_values("fantasy_points_ffs", ascending=False)
        .head(top)
    )
    typer.echo(f"Top {top} — {season} {ruleset}"
               + (f" ({position.upper()})" if position else ""))
    typer.echo(leaders_df.to_string(index=False))


@app.command()
def career(
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
    position: Annotated[str | None, typer.Option("--position", "-p")] = None,
    min_games: Annotated[int, typer.Option("--min-games", help="Filter out cameos")] = 16,
    sort: Annotated[str, typer.Option("--sort", help="ppg | total | best_week")] = "ppg",
    top: Annotated[int, typer.Option("--top")] = 25,
) -> None:
    """Career fantasy summary across all scored seasons."""
    df = career_mod.load_scored(ruleset=ruleset)
    summary = career_mod.career_summary(df)
    if position:
        summary = summary[summary["position"] == position.upper()]
    summary = summary[summary["games"] >= min_games]
    if sort not in summary.columns:
        raise typer.BadParameter(f"unknown sort {sort!r}")
    summary = summary.sort_values(sort, ascending=False).head(top)
    typer.echo(summary.to_string(index=False))


@app.command()
def rolling(
    player: Annotated[str, typer.Option("--player", help="Substring match on player name")],
    window: Annotated[int, typer.Option("--window", "-w")] = 8,
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
) -> None:
    """Show a player's rolling N-game fantasy points across their career."""
    df = career_mod.load_scored(ruleset=ruleset)
    mask = df["player_display_name"].str.contains(player, case=False, na=False)
    matches = df[mask]
    if matches.empty:
        raise typer.BadParameter(f"no player matching {player!r}")
    unique_ids = matches[["player_id", "player_display_name"]].drop_duplicates()
    if len(unique_ids) > 1:
        typer.echo("Multiple matches — refine your query:")
        typer.echo(unique_ids.to_string(index=False))
        raise typer.Exit(1)
    rolled = career_mod.rolling_fantasy(matches, window)
    cols = ["season", "week", "career_game", "fantasy_points_ffs", "fp_roll"]
    typer.echo(f"{unique_ids.iloc[0]['player_display_name']} — rolling {window}-game avg")
    typer.echo(rolled[cols].to_string(index=False))


@app.command()
def defense(
    season: Annotated[int, typer.Option("--season", "-s")],
    position: Annotated[str, typer.Option("--position", "-p")],
    last_n_weeks: Annotated[
        int | None, typer.Option("--last-n", help="Only aggregate over the last N weeks")
    ] = None,
    sort: Annotated[str, typer.Option("--sort", help="easiest | hardest")] = "easiest",
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
) -> None:
    """Rank defenses by fantasy points allowed to `position`."""
    if position.upper() not in matchups.SKILL_POSITIONS:
        raise typer.BadParameter(
            f"position must be one of {matchups.SKILL_POSITIONS}, got {position!r}"
        )
    scored = career_mod.load_scored([season], ruleset=ruleset)
    ranked = matchups.defense_ranking(
        scored, season=season, position=position.upper(), last_n_weeks=last_n_weeks
    )
    if sort == "hardest":
        ranked = ranked.iloc[::-1].reset_index(drop=True)
    elif sort != "easiest":
        raise typer.BadParameter("--sort must be 'easiest' or 'hardest'")
    label = f"last {last_n_weeks} weeks" if last_n_weeks else "full season"
    typer.echo(
        f"Defenses vs {position.upper()} — {season} ({label}), sorted {sort} first:"
    )
    typer.echo(ranked.to_string(index=False))


if __name__ == "__main__":
    app()
