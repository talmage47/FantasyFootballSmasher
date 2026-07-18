from __future__ import annotations

from typing import Annotated

import typer

from ffs import config, ingest, scoring

app = typer.Typer(help="Fantasy Football Smasher", no_args_is_help=True)


@app.command()
def fetch(
    seasons: Annotated[list[int], typer.Option("--season", "-s", help="Season to fetch")],
) -> None:
    """Download weekly NFL player stats and save to Parquet."""
    for season in seasons:
        typer.echo(f"Fetching weekly stats for {season}…")
        df = ingest.fetch_weekly(season)
        ingest.save_weekly(df, season)
        typer.echo(f"  → {len(df):,} rows saved to {config.weekly_raw_path(season)}")


@app.command()
def score(
    season: Annotated[int, typer.Option("--season", "-s")],
    ruleset: Annotated[str, typer.Option("--ruleset", "-r")] = "standard",
    top: Annotated[int, typer.Option("--top", help="Show top N by total points")] = 25,
) -> None:
    """Compute fantasy points for a season using the given ruleset."""
    if ruleset not in scoring.RULESETS:
        raise typer.BadParameter(f"unknown ruleset {ruleset!r}; known: {list(scoring.RULESETS)}")

    rules = scoring.RULESETS[ruleset]
    df = ingest.load_weekly(season)
    scored = scoring.score_weekly(df, rules)

    out_path = config.ensure_parent(config.weekly_scored_path(season, rules.name))
    scored.to_parquet(out_path, index=False)
    typer.echo(f"Scored {len(scored):,} rows → {out_path}")

    leaders = (
        scored.groupby(["player_id", "player_display_name", "position"], dropna=False)[
            "fantasy_points_ffs"
        ]
        .sum()
        .reset_index()
        .sort_values("fantasy_points_ffs", ascending=False)
        .head(top)
    )
    typer.echo(f"\nTop {top} — {season} {rules.name}:")
    typer.echo(leaders.to_string(index=False))


if __name__ == "__main__":
    app()
