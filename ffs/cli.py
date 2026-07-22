from __future__ import annotations

from typing import Annotated

import typer

from pathlib import Path

from ffs import career as career_mod
from ffs import config, draft, ingest, lineup, matchups, projections, scoring, sos

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


@app.command("fetch-adp")
def fetch_adp_cmd(
    force: Annotated[bool, typer.Option("--force", help="Refetch even if adp.parquet exists")] = False,
) -> None:
    """Fetch FantasyPros consensus redraft rankings (ADP proxy)."""
    path = config.adp_path()
    if path.exists() and not force:
        typer.echo(f"[skip] {path.name} already exists (use --force to refresh)")
        return
    typer.echo("Fetching FantasyPros redraft-overall + player id map…")
    df = ingest.fetch_adp()
    ingest.save_adp(df)
    matched = df["player_id"].notna().sum()
    typer.echo(
        f"  → {len(df):,} ranked players ({matched:,} joined to gsis_id) saved to {path}"
    )


@app.command("fetch-depth-charts")
def fetch_depth_charts_cmd(
    seasons: Annotated[list[int] | None, typer.Option("--season", "-s")] = None,
    start: Annotated[int | None, typer.Option("--start")] = None,
    end: Annotated[int | None, typer.Option("--end")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Download depth charts and save to Parquet."""
    for season in _resolve_seasons(seasons, start, end):
        path = config.depth_charts_path(season)
        if path.exists() and not force:
            typer.echo(f"[skip] {season}: {path.name} already exists")
            continue
        typer.echo(f"Fetching depth charts for {season}…")
        df = ingest.fetch_depth_charts(season)
        ingest.save_depth_charts(df, season)
        typer.echo(f"  → {len(df):,} rows saved to {path}")


@app.command("fetch-rosters")
def fetch_rosters_cmd(
    seasons: Annotated[list[int] | None, typer.Option("--season", "-s")] = None,
    start: Annotated[int | None, typer.Option("--start")] = None,
    end: Annotated[int | None, typer.Option("--end")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Download annual rosters and save to Parquet."""
    for season in _resolve_seasons(seasons, start, end):
        path = config.rosters_path(season)
        if path.exists() and not force:
            typer.echo(f"[skip] {season}: {path.name} already exists")
            continue
        typer.echo(f"Fetching roster for {season}…")
        df = ingest.fetch_rosters(season)
        ingest.save_rosters(df, season)
        typer.echo(f"  → {len(df):,} players saved to {path}")


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


@app.command("sos")
def sos_cmd(
    schedule_season: Annotated[int, typer.Option("--schedule-season", help="Season whose schedule to analyze")],
    position: Annotated[str, typer.Option("--position", "-p")],
    rankings_season: Annotated[
        int | None,
        typer.Option("--rankings-season", help="Season whose defense to use (default: schedule-season - 1)"),
    ] = None,
    start_week: Annotated[int | None, typer.Option("--start-week")] = None,
    end_week: Annotated[int | None, typer.Option("--end-week")] = None,
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
) -> None:
    """Strength of schedule per team vs a given position."""
    if position.upper() not in matchups.SKILL_POSITIONS:
        raise typer.BadParameter(f"position must be one of {matchups.SKILL_POSITIONS}")
    r_season = rankings_season if rankings_season is not None else schedule_season - 1
    schedule = ingest.load_schedules(schedule_season)
    scored = career_mod.load_scored([r_season], ruleset=ruleset)
    weeks = (start_week, end_week) if start_week and end_week else None
    result = sos.team_sos(
        schedule, scored, position=position.upper(), ranking_season=r_season, weeks=weeks
    )
    label = f"weeks {start_week}-{end_week}" if weeks else "full season"
    typer.echo(
        f"SoS for {schedule_season} vs {position.upper()} using {r_season} defenses ({label})"
    )
    typer.echo(result.to_string(index=False))


@app.command()
def project(
    season: Annotated[int, typer.Option("--season", "-s")],
    week: Annotated[int, typer.Option("--week", "-w")],
    position: Annotated[str | None, typer.Option("--position", "-p")] = None,
    window: Annotated[int, typer.Option("--window", help="Baseline: last N games")] = 8,
    rankings_season: Annotated[int | None, typer.Option("--rankings-season")] = None,
    top: Annotated[int, typer.Option("--top")] = 25,
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
) -> None:
    """Project fantasy points for a given week: baseline PPG × opponent adjustment."""
    scored, schedule, rosters_df, depth_charts_df = _load_projection_inputs(
        season, ruleset
    )
    positions = (
        (position.upper(),) if position else matchups.SKILL_POSITIONS
    )
    result = projections.project_week(
        scored,
        schedule,
        target_season=season,
        target_week=week,
        window=window,
        rankings_season=rankings_season,
        positions=positions,
        rosters_df=rosters_df,
        depth_charts_df=depth_charts_df,
    )
    if position:
        result = result[result["position"] == position.upper()]
    cols = [
        "player_display_name", "position", "team", "opponent",
        "baseline_ppg", "opp_factor", "projection",
    ]
    typer.echo(
        f"Projections — {season} week {week} (window={window})"
        + (f" [{position.upper()}]" if position else "")
    )
    typer.echo(result[cols].head(top).to_string(index=False))


def _load_projection_inputs(season: int, ruleset: str):
    scored = career_mod.load_scored(ruleset=ruleset)
    schedule = ingest.load_schedules(season)
    rosters_df = (
        ingest.load_rosters(season) if config.rosters_path(season).exists() else None
    )
    if rosters_df is None:
        typer.echo(
            f"[warn] no {season} roster on disk; teams will use last-played team. "
            f"Run `ffs fetch-rosters --season {season}` to fix."
        )
    depth_charts_df = (
        ingest.load_depth_charts(season)
        if config.depth_charts_path(season).exists()
        else None
    )
    if depth_charts_df is None:
        typer.echo(
            f"[warn] no {season} depth charts on disk; backups will pollute projections. "
            f"Run `ffs fetch-depth-charts --season {season}` to fix."
        )
    return scored, schedule, rosters_df, depth_charts_df


@app.command("project-season")
def project_season_cmd(
    season: Annotated[int, typer.Option("--season", "-s")],
    position: Annotated[str | None, typer.Option("--position", "-p")] = None,
    rankings_season: Annotated[int | None, typer.Option("--rankings-season")] = None,
    top: Annotated[int, typer.Option("--top")] = 40,
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
) -> None:
    """Project full-season fantasy points per player."""
    scored, schedule, rosters_df, depth_charts_df = _load_projection_inputs(season, ruleset)
    positions = (position.upper(),) if position else matchups.SKILL_POSITIONS
    result = projections.project_season(
        scored,
        schedule,
        target_season=season,
        rankings_season=rankings_season,
        positions=positions,
        rosters_df=rosters_df,
        depth_charts_df=depth_charts_df,
    )
    if position:
        result = result[result["position"] == position.upper()]
    cols = ["player_display_name", "position", "team",
            "games", "avg_opp_factor", "ppg", "projected_points"]
    typer.echo(
        f"Season projections — {season}"
        + (f" [{position.upper()}]" if position else "")
    )
    typer.echo(result[cols].head(top).to_string(index=False))


@app.command("draft")
def draft_cmd(
    season: Annotated[int, typer.Option("--season", "-s")],
    teams: Annotated[int, typer.Option("--teams", help="League size")] = 12,
    top: Annotated[int, typer.Option("--top")] = 100,
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
) -> None:
    """VBD-ranked draft board for the given season and league size."""
    scored, schedule, rosters_df, depth_charts_df = _load_projection_inputs(season, ruleset)
    season_proj = projections.project_season(
        scored,
        schedule,
        target_season=season,
        rosters_df=rosters_df,
        depth_charts_df=depth_charts_df,
    )
    board = draft.draft_rankings(season_proj, teams=teams)
    if config.adp_path().exists():
        board = draft.with_adp(board, ingest.load_adp())
        cols = ["overall_rank", "player_display_name", "position", "team",
                "pos_rank", "projected_points", "vbd", "adp", "adp_delta"]
    else:
        typer.echo(
            "[warn] no adp.parquet on disk; skipping market comparison. "
            "Run `ffs fetch-adp` to enable."
        )
        cols = ["overall_rank", "player_display_name", "position", "team",
                "pos_rank", "projected_points", "vbd", "replacement_pts"]
    typer.echo(
        f"Draft board — {season}, {teams}-team league "
        f"(1QB / 2RB / 2WR / 1TE / 1FLEX)"
    )
    typer.echo(board[cols].head(top).to_string(index=False))


@app.command("lineup")
def lineup_cmd(
    season: Annotated[int, typer.Option("--season", "-s")],
    week: Annotated[int, typer.Option("--week", "-w")],
    roster: Annotated[
        Path, typer.Option("--roster", help="File with one player name per line")
    ],
    window: Annotated[int, typer.Option("--window")] = 8,
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
) -> None:
    """Compute the optimal starting lineup for a given week from your roster."""
    if not roster.exists():
        raise typer.BadParameter(f"Roster file not found: {roster}")
    names = [line.strip() for line in roster.read_text().splitlines() if line.strip()]
    if not names:
        raise typer.BadParameter("Empty roster file")

    scored, schedule, rosters_df, depth_charts_df = _load_projection_inputs(
        season, ruleset
    )
    proj = projections.project_week(
        scored,
        schedule,
        target_season=season,
        target_week=week,
        window=window,
        rosters_df=rosters_df,
        depth_charts_df=depth_charts_df,
    )

    matched, unmatched = lineup.resolve_roster(proj, names)
    if unmatched:
        typer.echo(f"[warn] Not projected (backups, byes, or unknown): {'; '.join(unmatched)}")
    if matched.empty:
        raise typer.Exit(1)

    starters, bench = lineup.optimize_lineup(matched)
    total = starters["projection"].sum()
    typer.echo(
        f"\nOptimal lineup — {season} week {week} (projected total: {total:.1f} pts)"
    )
    starter_cols = ["slot", "player_display_name", "position", "team", "opponent", "projection"]
    typer.echo(starters[starter_cols].to_string(index=False))
    if not bench.empty:
        bench_cols = ["player_display_name", "position", "team", "opponent", "projection"]
        typer.echo("\nBench:")
        typer.echo(bench[bench_cols].to_string(index=False))


if __name__ == "__main__":
    app()
