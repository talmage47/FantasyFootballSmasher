from __future__ import annotations

from typing import Annotated

import typer

from pathlib import Path

from ffs import career as career_mod
from ffs import (
    config, draft, dst, ingest, injuries as injuries_mod,
    lineup, matchups, projections, scoring, sleeper, sos,
)

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
        "baseline_ppg", "opp_factor", "game_env_factor", "projection", "injury_status",
    ]
    cols = [c for c in cols if c in result.columns]
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
            "avg_opp_factor", "avg_game_env", "ppg", "projected_points", "injury_status"]
    cols = [c for c in cols if c in result.columns]
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
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
) -> None:
    """VBD-ranked draft board for the given season and league size."""
    if sleepers and reaches:
        raise typer.BadParameter("--sleepers and --reaches are mutually exclusive")

    scored, schedule, rosters_df, depth_charts_df, injuries_df = _load_projection_inputs(season, ruleset)
    season_proj = projections.project_season(
        scored,
        schedule,
        target_season=season,
        rosters_df=rosters_df,
        depth_charts_df=depth_charts_df,
        injuries_df=injuries_df,
    )
    board = draft.draft_rankings(season_proj, teams=teams)
    has_adp = config.adp_path().exists()
    if has_adp:
        adp = ingest.load_adp()
        board = draft.with_adp(board, adp)
        board = draft.with_rookies(board, adp)
    else:
        typer.echo(
            "[warn] no adp.parquet on disk; skipping market comparison. "
            "Run `ffs fetch-adp` to enable."
        )
    board = draft.with_tiers(board, teams=teams)

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
                "tier", "projected_points", "vbd", "adp", "adp_delta", "is_rookie",
                "injury_status"]
    else:
        cols = ["overall_rank", "player_display_name", "position", "team", "pos_rank",
                "tier", "projected_points", "vbd", "replacement_pts", "injury_status"]
    cols = [c for c in cols if c in board.columns]

    header = f"Draft board — {season}, {teams}-team league (1QB / 2RB / 2WR / 1TE / 1FLEX / 1K / 1DST)"
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
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
) -> None:
    """Compute the optimal starting lineup from a roster (text file OR Sleeper league)."""
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
    else:
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

    starters, bench = lineup.optimize_lineup(matched)
    total = starters["projection"].sum()
    typer.echo(
        f"\nOptimal lineup — {season} week {week} (projected total: {total:.1f} pts)"
    )
    starter_cols = ["slot", "player_display_name", "position", "team", "opponent", "projection", "injury_status"]
    starter_cols = [c for c in starter_cols if c in starters.columns]
    typer.echo(starters[starter_cols].to_string(index=False))
    if not bench.empty:
        bench_cols = ["player_display_name", "position", "team", "opponent", "projection", "injury_status"]
        bench_cols = [c for c in bench_cols if c in bench.columns]
        typer.echo("\nBench:")
        typer.echo(bench[bench_cols].to_string(index=False))


if __name__ == "__main__":
    app()
