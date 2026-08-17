from __future__ import annotations

from typing import Annotated

import pandas as pd
import typer

from pathlib import Path

from ffs import career as career_mod
from ffs import (
    config, draft, draftlive, dst, ingest, injuries as injuries_mod,
    lineup, matchups, platoon as platoon_mod, projections, scoring, sleeper, sos,
)

app = typer.Typer(help="Fantasy Football Smasher", no_args_is_help=True)


def _parse_roster_slots(
    spec: str | None,
) -> tuple[dict[str, int], dict[str, int]] | None:
    """Parse e.g. 'QB=1,RB=2,WR=2,TE=1,FLEX=2,SUPER_FLEX=1,K=1,DST=1' into
    (starters, flex_counts). Returns None if spec is None."""
    if spec is None:
        return None
    starters: dict[str, int] = {}
    flex_counts: dict[str, int] = {}
    for chunk in spec.split(","):
        if "=" not in chunk:
            raise typer.BadParameter(f"Bad --roster-slots entry {chunk!r}; expected POS=N")
        k, v = chunk.split("=", 1)
        key = k.strip().upper()
        try:
            n = int(v)
        except ValueError:
            raise typer.BadParameter(f"Bad slot count in {chunk!r}")
        if key in draft.FLEX_ELIGIBILITY:
            flex_counts[key] = n
        else:
            starters[key] = n
    return starters, flex_counts


def _load_league_slot_config(
    league_id: str,
) -> tuple[dict[str, int], dict[str, int]] | None:
    """Return (starters, flex_counts) parsed from the cached Sleeper league."""
    try:
        league, _rosters, _users = sleeper.load_league_snapshot(league_id)
    except FileNotFoundError:
        return None
    positions = league.get("roster_positions") or []
    if not positions:
        return None
    return draft.parse_sleeper_roster_positions(positions)


def _format_slots(starters: dict[str, int], flex_counts: dict[str, int]) -> str:
    parts = [f"{n}{p}" for p, n in starters.items()]
    parts.extend(f"{n}{name}" for name, n in flex_counts.items())
    return " / ".join(parts)


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


@app.command("fetch-ffc-adp")
def fetch_ffc_adp_cmd(
    scoring: Annotated[str, typer.Option("--scoring", "-r")] = "standard",
    teams: Annotated[int, typer.Option("--teams")] = 12,
    year: Annotated[int | None, typer.Option("--year")] = None,
    force: Annotated[bool, typer.Option("--force", help="Refetch even if ffc_adp.parquet exists")] = False,
) -> None:
    """Fetch Fantasy Football Calculator ADP (real 12-team mock drafts, updated daily)."""
    path = config.ffc_adp_path()
    if path.exists() and not force:
        typer.echo(f"[skip] {path.name} already exists (use --force to refresh)")
        return
    typer.echo(f"Fetching FFC ADP ({scoring}, {teams}-team)…")
    df = ingest.fetch_ffc_adp(scoring=scoring, teams=teams, year=year)
    meta = df.attrs.get("ffc_meta", {})
    ingest.save_ffc_adp(df)
    typer.echo(
        f"  → {len(df):,} players from {meta.get('total_drafts', '?')} drafts "
        f"({meta.get('start_date', '?')} → {meta.get('end_date', '?')}) saved to {path}"
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


@app.command("fetch-sleeper-league")
def fetch_sleeper_league_cmd(
    league_id: Annotated[str, typer.Option("--league-id", help="Sleeper league ID")],
    username: Annotated[
        str | None,
        typer.Option("--username", help="Print roster preview for this Sleeper display name"),
    ] = None,
    force_players: Annotated[
        bool,
        typer.Option("--force-players", help="Refresh the players.json cache even if fresh"),
    ] = False,
) -> None:
    """Cache a Sleeper league snapshot (settings, rosters, users, player map)."""
    typer.echo(f"Fetching Sleeper league {league_id}…")
    league = sleeper.fetch_league(league_id)
    rosters = sleeper.fetch_rosters(league_id)
    users = sleeper.fetch_users(league_id)
    out = sleeper.save_league_snapshot(league_id, league, rosters, users)
    typer.echo(
        f"  → league '{league.get('name')}' "
        f"({league.get('total_rosters')} teams, "
        f"{league.get('season')} {league.get('season_type')}) saved to {out}"
    )
    typer.echo("Refreshing Sleeper player map…")
    players_map = sleeper.load_or_fetch_players(force=force_players)
    typer.echo(f"  → {len(players_map):,} players cached at {config.sleeper_players_path()}")
    if username is not None:
        try:
            user, ids = sleeper.user_roster(league_id, username)
        except ValueError as e:
            raise typer.BadParameter(str(e))
        names = sleeper.resolve_player_names(ids, players_map)
        typer.echo(f"\nRoster for {user.get('display_name')} ({len(ids)} players):")
        for n in names:
            typer.echo(f"  {n}")


@app.command("fetch-injuries")
def fetch_injuries_cmd(
    seasons: Annotated[list[int] | None, typer.Option("--season", "-s")] = None,
    start: Annotated[int | None, typer.Option("--start")] = None,
    end: Annotated[int | None, typer.Option("--end")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Download weekly NFL injury reports."""
    for season in _resolve_seasons(seasons, start, end):
        path = config.injuries_path(season)
        if path.exists() and not force:
            typer.echo(f"[skip] {season}: {path.name} already exists")
            continue
        typer.echo(f"Fetching injuries for {season}…")
        df = ingest.fetch_injuries(season)
        ingest.save_injuries(df, season)
        typer.echo(f"  → {len(df):,} rows saved to {path}")


@app.command("fetch-team-stats")
def fetch_team_stats_cmd(
    seasons: Annotated[list[int] | None, typer.Option("--season", "-s")] = None,
    start: Annotated[int | None, typer.Option("--start")] = None,
    end: Annotated[int | None, typer.Option("--end")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Download per-team weekly stats (source of DST scoring)."""
    for season in _resolve_seasons(seasons, start, end):
        path = config.team_stats_path(season)
        if path.exists() and not force:
            typer.echo(f"[skip] {season}: {path.name} already exists")
            continue
        typer.echo(f"Fetching team stats for {season}…")
        df = ingest.fetch_team_stats(season)
        ingest.save_team_stats(df, season)
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

        ts_path = config.team_stats_path(season)
        sched_path = config.schedules_path(season)
        dst_out = config.dst_scored_path(season, rules.name)
        if not ts_path.exists() or not sched_path.exists():
            typer.echo(
                f"  [skip DST] need both team stats and schedule for {season}; "
                f"run `ffs fetch-team-stats --season {season}` and `ffs fetch-schedules --season {season}`."
            )
            continue
        team_stats = ingest.load_team_stats(season)
        schedule = ingest.load_schedules(season)
        dst_scored = dst.score_dst(team_stats, schedule)
        config.ensure_parent(dst_out)
        dst_scored.to_parquet(dst_out, index=False)
        typer.echo(f"  Scored {len(dst_scored):,} DST rows → {dst_out}")


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
    scored, schedule, rosters_df, depth_charts_df, injuries_df = _load_projection_inputs(
        season, ruleset
    )
    positions = (
        (position.upper(),) if position else matchups.PROJECTABLE_POSITIONS
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
        injuries_df=injuries_df,
    )
    if position:
        result = result[result["position"] == position.upper()]
    cols = [
        "player_display_name", "position", "team", "opponent",
        "baseline_ppg", "opp_factor", "game_env_factor",
        "floor", "projection", "ceiling", "injury_status",
    ]
    cols = [c for c in cols if c in result.columns]
    typer.echo(
        f"Projections — {season} week {week} (window={window})"
        + (f" [{position.upper()}]" if position else "")
    )
    typer.echo(result[cols].head(top).to_string(index=False))


def _resolve_roster_names(
    roster: Path | None, league_id: str | None, username: str | None
) -> list[str]:
    """Load roster player names from a text file OR a cached Sleeper snapshot."""
    if roster is None and league_id is None:
        raise typer.BadParameter("Provide either --roster FILE or --league-id ID (with --username)")
    if roster is not None and league_id is not None:
        raise typer.BadParameter("--roster and --league-id are mutually exclusive")
    if roster is not None:
        if not roster.exists():
            raise typer.BadParameter(f"Roster file not found: {roster}")
        names = [line.strip() for line in roster.read_text().splitlines() if line.strip()]
        if not names:
            raise typer.BadParameter("Empty roster file")
        return names
    if username is None:
        raise typer.BadParameter("--league-id requires --username")
    try:
        user, ids = sleeper.user_roster(league_id, username)
    except FileNotFoundError:
        raise typer.BadParameter(
            f"No cached Sleeper snapshot for league {league_id}. "
            f"Run `ffs fetch-sleeper-league --league-id {league_id}` first."
        )
    except ValueError as e:
        raise typer.BadParameter(str(e))
    players_map = sleeper.load_or_fetch_players()
    names = sleeper.resolve_player_names(ids, players_map)
    typer.echo(
        f"[sleeper] Loaded {len(names)} players for {user.get('display_name')} "
        f"from league {league_id}"
    )
    return names


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
    injuries_df, injuries_source_season = None, None
    for candidate in (season, season - 1):
        if config.injuries_path(candidate).exists():
            injuries_df = ingest.load_injuries(candidate)
            injuries_source_season = candidate
            break
    if injuries_df is None:
        typer.echo(
            f"[warn] no injuries on disk for {season} or {season - 1}; projections won't downweight Out/Doubtful/Questionable. "
            f"Run `ffs fetch-injuries --season {season}` to fix."
        )
    elif injuries_source_season != season:
        typer.echo(
            f"[info] using {injuries_source_season} injury data (no {season} report yet); "
            f"reflects end-of-{injuries_source_season} designations."
        )
    return scored, schedule, rosters_df, depth_charts_df, injuries_df


@app.command("project-season")
def project_season_cmd(
    season: Annotated[int, typer.Option("--season", "-s")],
    position: Annotated[str | None, typer.Option("--position", "-p")] = None,
    rankings_season: Annotated[int | None, typer.Option("--rankings-season")] = None,
    top: Annotated[int, typer.Option("--top")] = 40,
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
) -> None:
    """Project full-season fantasy points per player."""
    scored, schedule, rosters_df, depth_charts_df, injuries_df = _load_projection_inputs(season, ruleset)
    positions = (position.upper(),) if position else matchups.PROJECTABLE_POSITIONS
    result = projections.project_season(
        scored,
        schedule,
        target_season=season,
        rankings_season=rankings_season,
        positions=positions,
        rosters_df=rosters_df,
        depth_charts_df=depth_charts_df,
        injuries_df=injuries_df,
    )
    if position:
        result = result[result["position"] == position.upper()]
    cols = ["player_display_name", "position", "team", "games",
            "avg_opp_factor", "avg_game_env", "ppg",
            "floor", "projected_points", "ceiling", "injury_status"]
    cols = [c for c in cols if c in result.columns]
    typer.echo(
        f"Season projections — {season}"
        + (f" [{position.upper()}]" if position else "")
    )
    typer.echo(result[cols].head(top).to_string(index=False))


@app.command("schedule-player")
def schedule_player_cmd(
    season: Annotated[int, typer.Option("--season", "-s")],
    player: Annotated[str, typer.Option("--player", help="Player display name (fuzzy match)")],
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
) -> None:
    """Print week-by-week projections for a single player across the target season."""
    scored, schedule, rosters_df, depth_charts_df, _ = _load_projection_inputs(season, ruleset)
    weekly = projections.project_weekly(
        scored,
        schedule,
        target_season=season,
        rosters_df=rosters_df,
        depth_charts_df=depth_charts_df,
    )
    if weekly.empty:
        raise typer.BadParameter("No weekly projections available for this season")
    players_df = weekly[["player_id", "player_display_name"]].drop_duplicates()
    matched, unmatched = lineup.resolve_roster(players_df, [player])
    if unmatched or matched.empty:
        raise typer.BadParameter(f"no player matching {player!r}")
    pid = matched.iloc[0]["player_id"]
    name = matched.iloc[0]["player_display_name"]
    rows = weekly[weekly["player_id"] == pid].sort_values("week")
    cols = ["week", "opponent", "opp_factor", "game_env_factor", "week_projection"]
    typer.echo(f"{name} — {season} weekly schedule")
    typer.echo(rows[cols].to_string(index=False))


@app.command("draft")
def draft_cmd(
    season: Annotated[int, typer.Option("--season", "-s")],
    teams: Annotated[int, typer.Option("--teams", help="League size")] = 12,
    top: Annotated[int, typer.Option("--top")] = 100,
    position: Annotated[str | None, typer.Option("--position", "-p", help="Filter to a single position")] = None,
    after_pick: Annotated[
        int | None,
        typer.Option("--after-pick", help="Only show players with ADP >= N (best available at pick N)"),
    ] = None,
    sleepers: Annotated[
        bool, typer.Option("--sleepers", help="Sort by adp_delta desc (market drafts later than we do)")
    ] = False,
    reaches: Annotated[
        bool, typer.Option("--reaches", help="Sort by adp_delta asc (market drafts earlier than we do)")
    ] = False,
    exclude_out: Annotated[
        bool, typer.Option("--exclude-out", help="Drop players currently designated Out")
    ] = False,
    roster_slots: Annotated[
        str | None,
        typer.Option(
            "--roster-slots",
            help="Override starters, e.g. QB=1,RB=2,WR=2,TE=1,FLEX=2,SUPER_FLEX=1,K=1,DST=1",
        ),
    ] = None,
    league_id: Annotated[
        str | None,
        typer.Option("--league-id", help="Import starters/flex config from a cached Sleeper league"),
    ] = None,
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
) -> None:
    """VBD-ranked draft board for the given season and league size."""
    if sleepers and reaches:
        raise typer.BadParameter("--sleepers and --reaches are mutually exclusive")

    override = _parse_roster_slots(roster_slots)
    league_slots = _load_league_slot_config(league_id) if league_id else None
    if override is not None:
        starters, flex_counts = override
    elif league_slots is not None:
        starters, flex_counts = league_slots
        typer.echo(
            f"[sleeper] Using roster config from league {league_id}: "
            f"{_format_slots(starters, flex_counts)}"
        )
    else:
        starters = draft.DEFAULT_STARTERS
        flex_counts = draft.DEFAULT_FLEX_COUNTS

    scored, schedule, rosters_df, depth_charts_df, injuries_df = _load_projection_inputs(season, ruleset)
    season_proj = projections.project_season(
        scored,
        schedule,
        target_season=season,
        rosters_df=rosters_df,
        depth_charts_df=depth_charts_df,
        injuries_df=injuries_df,
    )
    board = draft.draft_rankings(
        season_proj, teams=teams, starters=starters, flex_counts=flex_counts
    )
    has_adp = config.adp_path().exists()
    has_ffc = config.ffc_adp_path().exists()
    ffc_df = ingest.load_ffc_adp() if has_ffc else None
    if has_adp:
        adp = ingest.load_adp()
        board = draft.with_adp(board, adp)
        if has_ffc:
            board = draft.with_ffc_adp(board, ffc_df)
        board = draft.with_rookies(board, adp, ffc=ffc_df)
        board = draft.with_hybrid_replacement(board, teams=teams)
    else:
        typer.echo(
            "[warn] no adp.parquet on disk; skipping market comparison. "
            "Run `ffs fetch-adp` to enable."
        )
        if has_ffc:
            board = draft.with_ffc_adp(board, ffc_df)
    board = draft.with_tiers(board, teams=teams, starters=starters, flex_counts=flex_counts)

    if "bye_week" not in board.columns:
        board["bye_week"] = pd.NA
    missing_bye = board["bye_week"].isna() & board["team"].notna()
    if missing_bye.any():
        team_bye = projections.team_bye_weeks(schedule, season).set_index("team")["bye_week"]
        board.loc[missing_bye, "bye_week"] = board.loc[missing_bye, "team"].map(team_bye)

    if exclude_out:
        if "injury_status" in board.columns:
            board = board[board["injury_status"] != "Out"]
    if position:
        board = board[board["position"] == position.upper()]
    if after_pick is not None:
        if not has_adp:
            raise typer.BadParameter("--after-pick requires ADP data; run `ffs fetch-adp` first")
        board = board[board["adp"].notna() & (board["adp"] >= after_pick)]
    if sleepers or reaches:
        if not has_adp:
            raise typer.BadParameter("--sleepers/--reaches require ADP data; run `ffs fetch-adp` first")
        draftable = teams * 18
        board = board[
            board["adp_delta"].notna()
            & (board["adp"] <= draftable)
            & (board["overall_rank"] <= draftable)
        ]
        if sleepers:
            board = board[board["adp_delta"] > 0].sort_values("adp_delta", ascending=False)
        else:
            board = board[board["adp_delta"] < 0].sort_values("adp_delta", ascending=True)

    if has_adp:
        cols = ["overall_rank", "player_display_name", "position", "team", "pos_rank",
                "tier", "bye_week", "floor", "projected_points", "ceiling", "vbd",
                "adp", "adp_delta", "ffc_adp", "ffc_delta", "is_rookie", "injury_status"]
    else:
        cols = ["overall_rank", "player_display_name", "position", "team", "pos_rank",
                "tier", "bye_week", "floor", "projected_points", "ceiling", "vbd",
                "replacement_pts", "injury_status"]
    cols = [c for c in cols if c in board.columns]

    slot_pretty = _format_slots(starters, flex_counts)
    header = f"Draft board — {season}, {teams}-team league ({slot_pretty}, {ruleset})"
    filters = []
    if position:
        filters.append(f"position={position.upper()}")
    if after_pick is not None:
        filters.append(f"after pick {after_pick}")
    if sleepers:
        filters.append("sleepers")
    if reaches:
        filters.append("reaches")
    if exclude_out:
        filters.append("exclude Out")
    if filters:
        header += "  [" + ", ".join(filters) + "]"
    typer.echo(header)
    typer.echo(board[cols].head(top).to_string(index=False))


@app.command("lineup")
def lineup_cmd(
    season: Annotated[int, typer.Option("--season", "-s")],
    week: Annotated[int, typer.Option("--week", "-w")],
    roster: Annotated[
        Path | None, typer.Option("--roster", help="File with one player name per line")
    ] = None,
    league_id: Annotated[
        str | None,
        typer.Option("--league-id", help="Sleeper league ID (alternative to --roster)"),
    ] = None,
    username: Annotated[
        str | None,
        typer.Option("--username", help="Sleeper display name whose roster to load"),
    ] = None,
    window: Annotated[int, typer.Option("--window")] = 8,
    roster_slots: Annotated[
        str | None,
        typer.Option(
            "--roster-slots",
            help="Override starting slots, e.g. QB=1,RB=2,WR=2,TE=1,FLEX=1,K=1,DST=1",
        ),
    ] = None,
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
) -> None:
    """Compute the optimal starting lineup from a roster (text file OR Sleeper league)."""
    names = _resolve_roster_names(roster, league_id, username)

    scored, schedule, rosters_df, depth_charts_df, injuries_df = _load_projection_inputs(
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
        injuries_df=injuries_df,
    )

    matched, unmatched = lineup.resolve_roster(proj, names)
    if unmatched:
        typer.echo(f"[warn] Not projected (backups, byes, or unknown): {'; '.join(unmatched)}")
    if "injury_status" in matched.columns:
        flagged = matched[matched["injury_status"].isin(["Out", "Doubtful", "Questionable"])]
        if not flagged.empty:
            summary = "; ".join(
                f"{r.player_display_name} ({r.injury_status})"
                for r in flagged.itertuples()
            )
            typer.echo(f"[injury] {summary}")
    if matched.empty:
        raise typer.Exit(1)

    override = _parse_roster_slots(roster_slots)
    if override is not None:
        starters_dict, flex_counts = override
        slots_spec = {**starters_dict, **flex_counts}
    elif league_id is not None:
        league_slots = _load_league_slot_config(league_id)
        if league_slots is not None:
            starters_dict, flex_counts = league_slots
            slots_spec = {**starters_dict, **flex_counts}
            typer.echo(
                f"[sleeper] Using roster config from league {league_id}: "
                f"{_format_slots(starters_dict, flex_counts)}"
            )
        else:
            slots_spec = lineup.DEFAULT_LINEUP
    else:
        slots_spec = lineup.DEFAULT_LINEUP
    starters, bench = lineup.optimize_lineup(matched, slots=slots_spec)
    total = starters["projection"].sum()
    typer.echo(
        f"\nOptimal lineup — {season} week {week} (projected total: {total:.1f} pts)"
    )
    starter_cols = ["slot", "player_display_name", "position", "team", "opponent",
                    "floor", "projection", "ceiling", "injury_status"]
    starter_cols = [c for c in starter_cols if c in starters.columns]
    typer.echo(starters[starter_cols].to_string(index=False))
    if not bench.empty:
        bench_cols = ["player_display_name", "position", "team", "opponent",
                      "floor", "projection", "ceiling", "injury_status"]
        bench_cols = [c for c in bench_cols if c in bench.columns]
        typer.echo("\nBench:")
        typer.echo(bench[bench_cols].to_string(index=False))


@app.command("platoon")
def platoon_cmd(
    season: Annotated[int, typer.Option("--season", "-s")],
    slot: Annotated[str, typer.Option("--slot", help="RB | WR | TE | FLEX")],
    roster: Annotated[
        Path | None, typer.Option("--roster", help="File with one player name per line")
    ] = None,
    league_id: Annotated[
        str | None, typer.Option("--league-id", help="Sleeper league ID (alternative to --roster)")
    ] = None,
    username: Annotated[
        str | None, typer.Option("--username", help="Sleeper display name whose roster to load")
    ] = None,
    top: Annotated[int, typer.Option("--top")] = 20,
    show_grid: Annotated[
        bool, typer.Option("--show-grid", help="Print week-by-week grid for anchor + top candidate")
    ] = False,
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
) -> None:
    """Rank bench candidates by weekly-complementary value against your roster anchor."""
    slot_u = slot.upper()
    if slot_u == "FLEX":
        pool_positions = platoon_mod.FLEX_POSITIONS
    elif slot_u in platoon_mod.FLEX_POSITIONS:
        pool_positions = (slot_u,)
    else:
        raise typer.BadParameter("--slot must be one of RB, WR, TE, FLEX")

    names = _resolve_roster_names(roster, league_id, username)
    scored, schedule, rosters_df, depth_charts_df, _ = _load_projection_inputs(season, ruleset)
    weekly = projections.project_weekly(
        scored,
        schedule,
        target_season=season,
        rosters_df=rosters_df,
        depth_charts_df=depth_charts_df,
    )
    if weekly.empty:
        raise typer.BadParameter("No weekly projections available for this season")

    players_df = weekly[["player_id", "player_display_name", "position", "team"]].drop_duplicates("player_id")
    matched, unmatched = lineup.resolve_roster(players_df, names)
    if unmatched:
        typer.echo(f"[warn] Not matched: {'; '.join(unmatched)}")
    if matched.empty:
        raise typer.BadParameter("No roster players matched projections")

    season_pts = weekly.groupby("player_id")["week_projection"].sum().rename("season_pts")
    matched = matched.merge(season_pts, on="player_id", how="left")
    slot_matched = matched[matched["position"].isin(pool_positions)]
    if slot_matched.empty:
        raise typer.BadParameter(f"No roster players at slot {slot_u}")
    anchor = slot_matched.sort_values("season_pts", ascending=False).iloc[0]
    anchor_pid = anchor["player_id"]

    roster_ids = set(matched["player_id"])
    pool = (
        weekly[weekly["position"].isin(pool_positions) & ~weekly["player_id"].isin(roster_ids)]
        [["player_id"]]
        .drop_duplicates()
    )
    result = platoon_mod.platoon_value(weekly, anchor_pid, pool)

    typer.echo(
        f"Platoon candidates — {season} slot={slot_u}, anchor={anchor['player_display_name']} "
        f"({anchor['position']}/{anchor['team']}, {anchor['season_pts']:.1f} pts projected)"
    )
    cols = ["player_display_name", "position", "team",
            "platoon_points_added", "weeks_candidate_starts", "bye_covered"]
    typer.echo(result[cols].head(top).to_string(index=False))

    if show_grid and not result.empty:
        top_pid = result.iloc[0]["player_id"]
        top_name = result.iloc[0]["player_display_name"]
        grid = platoon_mod.platoon_grid(weekly, anchor_pid, top_pid)
        typer.echo(f"\nWeek-by-week grid — {anchor['player_display_name']} vs {top_name}")
        typer.echo(grid.to_string(index=False))


def _build_draft_board(
    season: int,
    ruleset: str,
    teams: int,
    starters: dict[str, int],
    flex_counts: dict[str, int],
) -> pd.DataFrame:
    """Compute the full VBD board with ADP + tiers + bye_week, ready for live filtering."""
    scored, schedule, rosters_df, depth_charts_df, injuries_df = _load_projection_inputs(
        season, ruleset
    )
    season_proj = projections.project_season(
        scored, schedule, target_season=season,
        rosters_df=rosters_df, depth_charts_df=depth_charts_df, injuries_df=injuries_df,
    )
    board = draft.draft_rankings(
        season_proj, teams=teams, starters=starters, flex_counts=flex_counts
    )
    has_adp = config.adp_path().exists()
    has_ffc = config.ffc_adp_path().exists()
    ffc_df = ingest.load_ffc_adp() if has_ffc else None
    if has_adp:
        adp_df = ingest.load_adp()
        board = draft.with_adp(board, adp_df)
        if has_ffc:
            board = draft.with_ffc_adp(board, ffc_df)
        board = draft.with_rookies(board, adp_df, ffc=ffc_df)
        board = draft.with_hybrid_replacement(board, teams=teams)
    board = draft.with_tiers(
        board, teams=teams, starters=starters, flex_counts=flex_counts
    )
    if "bye_week" not in board.columns:
        board["bye_week"] = pd.NA
    missing_bye = board["bye_week"].isna() & board["team"].notna()
    if missing_bye.any():
        team_bye = projections.team_bye_weeks(schedule, season).set_index("team")["bye_week"]
        board.loc[missing_bye, "bye_week"] = board.loc[missing_bye, "team"].map(team_bye)
    return board


def _build_sleeper_to_gsis(players_map: dict[str, dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for sid, meta in players_map.items():
        gid = meta.get("gsis_id")
        if gid:
            out[sid] = gid
    for team_abbr in dst.TEAM_NICKNAMES:
        out[team_abbr] = f"DST-{team_abbr}"
    return out


def _render_draft_live(
    board: pd.DataFrame,
    picks: list[dict],
    sleeper_to_gsis: dict[str, str],
    my_user_id: str,
    my_slot: int,
    teams: int,
    rounds: int,
    starters: dict[str, int],
    flex_counts: dict[str, int],
    top_n: int,
    favorite_team: str | None,
    err: str | None,
):
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    drafted_ids = draftlive.build_drafted_set(picks, sleeper_to_gsis)
    my_pick_ids = draftlive.build_drafted_set(
        [p for p in picks if p.get("picked_by") == my_user_id], sleeper_to_gsis
    )
    my_roster = board[board["player_id"].isin(my_pick_ids)]
    my_positions = my_roster["position"].tolist()
    total_picks = teams * rounds
    current_pick = min(len(picks) + 1, total_picks)
    round_n = draftlive.current_round(current_pick, teams)
    on_the_clock = draftlive.slot_on_the_clock(current_pick, teams)
    next_pick = draftlive.next_own_pick(current_pick, my_slot, teams, rounds)

    wait_cost = draftlive.wait_cost_by_position(board, drafted_ids, next_pick)
    need = draftlive.positional_need(my_positions, starters, flex_counts)
    lock_out = ("K", "DST") if round_n < draftlive.K_DST_UNLOCK_ROUND else ()
    scored = draftlive.score_candidates(board, drafted_ids, need, wait_cost, lock_out_positions=lock_out)
    scored_all_pos = draftlive.score_candidates(board, drafted_ids, need, wait_cost)
    top5 = scored.head(top_n)
    top_pos = draftlive.top_per_position(scored_all_pos, board, drafted_ids, wait_cost)

    # anchors: best player at each position on your roster
    anchors_bye: dict[str, int] = {}
    if not my_roster.empty:
        for pos_key, grp in my_roster.groupby("position"):
            best = grp.sort_values("projected_points", ascending=False).iloc[0]
            if pd.notna(best.get("bye_week")):
                anchors_bye[pos_key] = int(best["bye_week"])

    def _draft_state_panel() -> Panel:
        picks_away = (next_pick - current_pick) if next_pick else None
        parts = [f"[bold]Round {round_n}[/bold]  ·  Pick {current_pick}  ·  Slot {on_the_clock} on the clock"]
        if next_pick is not None:
            parts.append(f"Your next pick: [bold cyan]{next_pick}[/bold cyan] ({picks_away} away)")
        else:
            parts.append("You are done drafting")
        recent = picks[-3:]
        for p in recent:
            meta = p.get("metadata") or {}
            name = f"{meta.get('first_name','?')} {meta.get('last_name','?')}"
            pos = meta.get("position", "?")
            team = meta.get("team", "?")
            parts.append(f"  pick {p.get('pick_no')}: {name} ({pos}/{team})")
        if err:
            parts.append(f"[red]poll error: {err}[/red]")
        return Panel("\n".join(parts), title="Draft", border_style="cyan")

    def _roster_panel() -> Panel:
        by_pos: dict[str, list[str]] = {}
        for _, r in my_roster.iterrows():
            bye = f"bye {int(r['bye_week'])}" if pd.notna(r.get("bye_week")) else "bye ?"
            by_pos.setdefault(r["position"], []).append(
                f"{r['player_display_name']} ({r['team']}, {bye})"
            )
        slot_order = ["QB", "RB", "WR", "TE", "K", "DST"]
        lines = []
        for pos in slot_order:
            required = starters.get(pos, 0)
            filled = by_pos.get(pos, [])
            for i in range(max(required, len(filled))):
                lines.append(f"  {pos:<4} {filled[i] if i < len(filled) else '—'}")
        shortfall = draftlive.remaining_starter_slots(my_positions, starters, flex_counts)
        if shortfall:
            lines.append("")
            lines.append("Still need: " + ", ".join(f"{n} {p}" for p, n in shortfall.items()))
        else:
            lines.append("")
            lines.append("Starting lineup filled")
        byes = [int(r["bye_week"]) for _, r in my_roster.iterrows() if pd.notna(r.get("bye_week"))]
        if byes:
            bye_counts: dict[int, int] = {}
            for b in byes:
                bye_counts[b] = bye_counts.get(b, 0) + 1
            stacks = [f"W{w}×{n}" for w, n in sorted(bye_counts.items()) if n > 1]
            if stacks:
                lines.append("Bye stack: " + ", ".join(stacks))
        return Panel("\n".join(lines) or "—", title="Your team", border_style="green")

    def _pos_table() -> Panel:
        t = Table.grid(padding=(0, 1))
        t.add_column("pos", style="bold")
        t.add_column("player"); t.add_column("team"); t.add_column("bye")
        t.add_column("vbd", justify="right"); t.add_column("tier", justify="right")
        t.add_column("wait", justify="right")
        for _, r in top_pos.iterrows():
            bye = str(int(r["bye_week"])) if pd.notna(r.get("bye_week")) else "?"
            tier = str(int(r["tier"])) if pd.notna(r.get("tier")) else "?"
            t.add_row(
                r["position"], r["player_display_name"], str(r.get("team") or ""),
                bye, f"{r.get('vbd', 0):.0f}", tier, f"{r.get('wait_cost', 0):.0f}"
            )
        return Panel(t, title="Best available by position", border_style="magenta")

    def _top5_panel() -> Panel:
        t = Table.grid(padding=(0, 1))
        t.add_column("#", style="bold")
        t.add_column("player"); t.add_column("pos"); t.add_column("team"); t.add_column("bye")
        t.add_column("vbd", justify="right"); t.add_column("wait", justify="right")
        t.add_column("fit", justify="right")
        t.add_column("why")
        for i, (_, r) in enumerate(top5.iterrows(), 1):
            bye = str(int(r["bye_week"])) if pd.notna(r.get("bye_week")) else "?"
            why = draftlive.explain_candidate(
                r, starters, my_positions, anchors_bye, next_pick
            )
            t.add_row(
                str(i), r["player_display_name"], r["position"], str(r.get("team") or ""),
                bye, f"{r.get('vbd', 0):.0f}", f"{r.get('wait_cost', 0):.0f}",
                f"{r.get('fit_score', 0):.0f}", why,
            )
        title = f"Top {top_n} for you"
        if lock_out:
            title += f"  (K/DST unlock at round {draftlive.K_DST_UNLOCK_ROUND})"
        return Panel(t, title=title, border_style="yellow")

    def _fav_panel() -> Panel | None:
        if favorite_team is None:
            return None
        pick = draftlive.favorite_team_pick(board, drafted_ids, favorite_team)
        if pick is None:
            body = f"No {favorite_team} players remaining."
        else:
            top_leader_fit = float(top5.iloc[0]["fit_score"]) if not top5.empty else 0.0
            fav_fit = float(pick.get("vbd", 0))
            gap = top_leader_fit - fav_fit
            bye = int(pick["bye_week"]) if pd.notna(pick.get("bye_week")) else "?"
            body = (
                f"{pick['player_display_name']}  {pick['position']}/{pick['team']}  "
                f"vbd {pick.get('vbd', 0):.0f}  bye {bye}\n"
                f"  {gap:.0f} points behind top overall fit"
            )
        return Panel(body, title=f"{favorite_team} watch", border_style="red")

    layout = Layout()
    sections = [
        Layout(_draft_state_panel(), size=6, name="state"),
        Layout(_roster_panel(), size=14, name="roster"),
        Layout(_pos_table(), size=10, name="pos"),
        Layout(_top5_panel(), size=10, name="top5"),
    ]
    fav = _fav_panel()
    if fav is not None:
        sections.append(Layout(fav, size=5, name="fav"))
    layout.split_column(*sections)
    return layout


@app.command("draft-live")
def draft_live_cmd(
    league_id: Annotated[str, typer.Option("--league-id", help="Sleeper league ID")],
    username: Annotated[str, typer.Option("--username", help="Your Sleeper display name")],
    season: Annotated[int, typer.Option("--season", "-s")] = 2026,
    draft_id: Annotated[
        str | None,
        typer.Option("--draft-id", help="Override auto-lookup from league_id"),
    ] = None,
    favorite_team: Annotated[
        str | None,
        typer.Option("--favorite-team", help="Team abbrev (e.g. SF) to always suggest an option from"),
    ] = None,
    poll: Annotated[int, typer.Option("--poll", help="Seconds between Sleeper API polls")] = 3,
    top: Annotated[int, typer.Option("--top", help="Candidates in the Top-N panel")] = 5,
    slot_override: Annotated[
        int | None,
        typer.Option("--slot", help="Manually set your draft slot if Sleeper hasn't assigned it yet"),
    ] = None,
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
) -> None:
    """Live-updating draft assistant: polls Sleeper and shows scored candidates in real time."""
    import threading
    import time

    from rich.console import Console
    from rich.live import Live

    console = Console()

    try:
        if draft_id is None:
            console.print(f"[cyan]Looking up latest draft for league {league_id}...[/cyan]")
            draft_info = sleeper.latest_draft(league_id)
            draft_id = draft_info["draft_id"]
        else:
            draft_info = sleeper.fetch_draft(draft_id)
    except Exception as e:
        raise typer.BadParameter(f"Could not resolve draft: {e}")
    settings = draft_info.get("settings") or {}
    teams = int(settings.get("teams") or 12)
    rounds = int(settings.get("rounds") or 15)
    console.print(f"[cyan]Draft {draft_id}: {teams} teams × {rounds} rounds ({draft_info.get('status')})[/cyan]")

    try:
        league, _rosters, users = sleeper.load_league_snapshot(league_id)
    except FileNotFoundError:
        raise typer.BadParameter(
            f"No cached Sleeper snapshot for league {league_id}. "
            f"Run `ffs fetch-sleeper-league --league-id {league_id}` first."
        )
    match = [u for u in users if u.get("display_name", "").lower() == username.lower()]
    if not match:
        available = ", ".join(u.get("display_name", "?") for u in users)
        raise typer.BadParameter(f"No user {username!r} in league. Available: {available}")
    my_user = match[0]
    my_user_id = my_user["user_id"]

    my_slot = slot_override or sleeper.user_draft_slot(draft_info, my_user_id)
    if my_slot is None:
        raise typer.BadParameter(
            "Draft slot not assigned yet in Sleeper. Pass --slot N once you know it."
        )
    console.print(f"[cyan]You are {my_user.get('display_name')} at draft slot {my_slot}[/cyan]")

    positions = league.get("roster_positions") or []
    starters, flex_counts = draft.parse_sleeper_roster_positions(positions)
    if not starters:
        starters = draft.DEFAULT_STARTERS
        flex_counts = draft.DEFAULT_FLEX_COUNTS
        console.print("[yellow][warn] no roster_positions in league; defaults applied[/yellow]")
    else:
        console.print(f"[cyan]Roster: {_format_slots(starters, flex_counts)}[/cyan]")

    console.print("[cyan]Building draft board (loading scored data + projections)...[/cyan]")
    board = _build_draft_board(season, ruleset, teams, starters, flex_counts)

    console.print("[cyan]Loading Sleeper player map...[/cyan]")
    players_map = sleeper.load_or_fetch_players()
    sleeper_to_gsis = _build_sleeper_to_gsis(players_map)

    state = {"picks": [], "err": None}
    lock = threading.Lock()
    stop = threading.Event()

    def poll_loop():
        while not stop.is_set():
            try:
                new_picks = sleeper.fetch_draft_picks(draft_id) or []
                with lock:
                    state["picks"] = new_picks
                    state["err"] = None
            except Exception as e:
                with lock:
                    state["err"] = str(e)[:120]
            stop.wait(poll)

    def render():
        with lock:
            picks = list(state["picks"])
            err = state["err"]
        return _render_draft_live(
            board, picks, sleeper_to_gsis, my_user_id, my_slot,
            teams, rounds, starters, flex_counts, top, favorite_team, err,
        )

    poll_thread = threading.Thread(target=poll_loop, daemon=True)
    poll_thread.start()

    try:
        with Live(render(), refresh_per_second=2, screen=True) as live:
            while not stop.is_set():
                time.sleep(0.5)
                live.update(render())
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
    console.print("[cyan]Exited draft-live[/cyan]")


if __name__ == "__main__":
    app()
