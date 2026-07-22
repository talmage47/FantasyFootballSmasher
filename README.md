# FantasyFootballSmasher (ffs)

A personal-use CLI that ingests NFL data, projects fantasy points, and
produces draft boards and weekly lineup recommendations. Designed for a
12-team, standard-scoring, redraft league with a 1QB / 2RB / 2WR / 1TE /
1FLEX starting lineup; the defaults can be overridden where it matters.

## What it does

**Data pipeline** (all files under `data/`, gitignored):
- Weekly player stats (`data/raw/weekly/<season>.parquet`) via
  [`nflreadpy`](https://nflreadpy.nflverse.com/) — one file per season.
- Schedules (`data/raw/schedules/<season>.parquet`) — includes Vegas
  `spread_line` and `total_line`.
- Rosters (`data/raw/rosters/<season>.parquet`) — the authoritative
  current-team lookup for offseason moves.
- Depth charts (`data/raw/depth_charts/<season>.parquet`) — full
  snapshot history; latest snapshot per player is used to filter out
  backups.
- ADP (`data/raw/adp.parquet`) — FantasyPros redraft-overall ECR joined
  to `gsis_id` via `load_ff_playerids`.

**Scoring:**
- `ffs/scoring.py` defines rules as a dict of `{stat_column: multiplier}`.
  `STANDARD` matches nflreadpy's built-in `fantasy_points` for a spot
  check (Josh Allen 2025 wk 1 = 38.76 in both).
- Scored data lands in `data/processed/weekly/<ruleset>/<season>.parquet`
  alongside the raw stats for ad-hoc DuckDB queries.

**Analytical layers:**
- `career` — cross-season aggregation and rolling per-player views.
- `matchups` — per-game fantasy points allowed by each defense to each
  position, ranked and league-relative.
- `sos` — strength of schedule per team, using any season's schedule
  and any (prior) season's defensive rankings.
- `projections` — baselines × opponent adjustment. Per-week projections use
  a rolling last-N-game PPG (recent form); season projections use a weighted
  blend of the last 3 seasons (60/30/10, most recent first) so career-year
  outliers regress. Roster override for offseason moves; depth chart filter
  to exclude backups; recency filter to drop retired players.
- `draft` — value-based drafting (VBD) with configurable league size,
  optionally enriched with market ADP so you can spot values vs reaches, and
  rookies interpolated in from the ADP file when a `gsis_id` can't be joined.
- `lineup` — greedy optimal starter selection from a roster of player
  names, given weekly projections.

## Storage choices

**Parquet + DuckDB, not SQLite.** Every dataset is a plain
column-oriented Parquet file. DuckDB can query the raw files directly
with SQL:

```python
import duckdb
duckdb.sql("""
  select player_display_name, avg(fantasy_points_ffs) as ppg
  from 'data/processed/weekly/standard/*.parquet'
  where position = 'RB' and season = 2025
  group by 1
  order by ppg desc
  limit 20
""").df()
```

Append-heavy, read-heavy, mutate-rarely — Parquet is the right fit. If
concurrent writes or heavy row-level mutation ever become a need, revisit.

## Install

Requires Python 3.11+ and [uv](https://github.com/astral-sh/uv).

```bash
brew install uv           # if not already installed
uv sync                    # creates .venv and installs deps
```

All commands run inside the virtualenv via `uv run`, or you can activate
it (`source .venv/bin/activate`) and drop the prefix.

## One-time backfill

Fetch everything you need for a full draft-prep session. Each command is
idempotent (skips existing Parquet files unless `--force` is passed).

```bash
uv run ffs fetch                          # weekly stats, defaults to 2016-2025
uv run ffs fetch-schedules                # schedules for the same range
uv run ffs fetch-schedules --season 2026  # + upcoming season's schedule
uv run ffs fetch-rosters --season 2026    # current-team assignments
uv run ffs fetch-depth-charts --season 2026  # starter / backup ordering
uv run ffs fetch-adp                      # FantasyPros consensus rankings
uv run ffs score                          # compute standard fantasy points
```

Total data footprint: ~20 MB.

## Command reference

Every command supports `--help` for full options.

### Ingest

| Command | Purpose |
|---|---|
| `ffs fetch [--season Y \| --start Y --end Y] [--force]` | Weekly stats. Defaults to `DEFAULT_SEASONS` (2016–2025). |
| `ffs fetch-schedules ...` | Season schedules. Same flags. |
| `ffs fetch-rosters ...` | Annual rosters. |
| `ffs fetch-depth-charts ...` | Depth charts (all snapshots preserved). |
| `ffs fetch-adp [--force]` | FantasyPros redraft-overall ECR, no season needed. |

### Scoring / views

| Command | Purpose |
|---|---|
| `ffs score [--season Y \| --start Y --end Y] [--ruleset standard] [--force]` | Compute fantasy points and write `processed/` Parquet. Defaults to all seasons. |
| `ffs leaders --season Y [--position P] [--top N]` | Top scorers for a single season. |
| `ffs career [--position P] [--min-games 16] [--sort ppg\|total\|best_week] [--top N]` | Career per-player aggregates across all scored seasons. |
| `ffs rolling --player NAME [--window 8]` | Rolling N-game PPG across a player's whole career (spans seasons). |
| `ffs schedule --season Y [--week W]` | Matchups with scores and Vegas lines. |

### Matchup analysis

| Command | Purpose |
|---|---|
| `ffs defense --season Y --position P [--last-n N] [--sort easiest\|hardest]` | Ranks all 32 defenses by fantasy points allowed to a given position. |
| `ffs sos --schedule-season Y --position P [--rankings-season Y2] [--start-week --end-week]` | Team-level strength of schedule vs position. `rankings-season` defaults to `schedule-season − 1`. |

### Projections and draft

| Command | Purpose |
|---|---|
| `ffs project --season Y --week W [--position P] [--window 8] [--top 25]` | Per-week projections: baseline PPG × opponent adjustment. |
| `ffs project-season --season Y [--position P] [--window 17] [--top 40]` | Full-season projections (sums weekly projections). |
| `ffs draft --season Y [--teams 12] [--top 100]` | VBD-ranked draft board across all positions, enriched with ADP if `adp.parquet` is present. |
| `ffs lineup --season Y --week W --roster ROSTER.txt [--window 8]` | Optimal starting lineup from a text file of player names. |

## Typical workflows

### Pre-draft analysis (July / August)

```bash
# One-time refresh of everything current-season
uv run ffs fetch-schedules --season 2026 --force
uv run ffs fetch-rosters   --season 2026 --force
uv run ffs fetch-depth-charts --season 2026 --force
uv run ffs fetch-adp --force

# Full-season projections + VBD draft board with ADP
uv run ffs draft --season 2026 --top 100

# Positional slice
uv run ffs project-season --season 2026 --position WR --top 20
```

The `adp_delta` column on the draft board is the most useful new
signal: **positive** = market drafts them later than we rank them
(potential values you can wait on); **negative** = market is more
bullish than the model.

### In-season, weekly

```bash
# After each Sunday, refresh weekly stats and rescore
uv run ffs fetch --season 2026
uv run ffs score --season 2026

# Optional: refresh depth charts and rosters (injuries, waivers, trades)
uv run ffs fetch-depth-charts --season 2026 --force

# Weekly start/sit for your roster
uv run ffs lineup --season 2026 --week 5 --roster my_roster.txt
```

### Ad-hoc analysis

```bash
# How do the Vikings treat opposing WRs, last 4 weeks?
uv run ffs defense --season 2025 --position WR --last-n 4 --sort hardest

# Saquon Barkley's whole career, rolling 8-game avg
uv run ffs rolling --player "Saquon" --window 8

# Which teams have the toughest 2026 WR schedules?
uv run ffs sos --schedule-season 2026 --position WR --sort hardest
```

## Roster file format

For `ffs lineup`, one player display name per line. Comments and blanks
are stripped. Fuzzy matching handles case and punctuation
(`Ja'Marr Chase`, `A.J. Brown`, `Amon-Ra St. Brown` all match). Backups
excluded by the depth chart filter will be reported as unmatched.

```
Josh Allen
Bijan Robinson
Saquon Barkley
Puka Nacua
Ja'Marr Chase
Trey McBride
...
```

## Project layout

```
ffs/
  config.py       # data paths, DEFAULT_SEASONS
  ingest.py       # fetch/save/load for every data source
  scoring.py      # ScoringRules dataclass + STANDARD ruleset
  career.py       # load_scored, rolling views, career aggregates
  matchups.py     # points_allowed_by_game, defense_ranking
  sos.py          # opponents_by_team, team_sos
  projections.py  # player_baseline, project_week, project_season
  draft.py        # replacement_ranks, draft_rankings, with_adp
  lineup.py       # resolve_roster, optimize_lineup
  cli.py          # typer app (all commands live here)
```

Every module is a plain function or dataclass over Pandas DataFrames.
No abstract base classes, no plugins, no ORM. Adding a new dataset or
scoring format is a new dict, not a new class hierarchy.

## Known limitations

- **No K / DST projections yet** — scoring rules and depth filter both
  skip them. Lineups and draft boards only cover QB/RB/WR/TE.
- **Rookie projections are market-derived, not model-derived** — rookies
  have no NFL games so the baseline can't produce anything. `draft` merges
  unmatched FantasyPros entries and interpolates projected points from
  same-position veterans on the `(adp, projected_points)` curve. Rookies
  are flagged in the `is_rookie` column.
- **No opportunity model** — a player's baseline is their historical
  PPG, not a snap-share × team-context estimate. A backup who inherits
  a starting role won't have his projection change until games happen.
- **No variance / floor-ceiling** — projections are point estimates.
- **No league integration yet** — rosters come from a text file, not
  ESPN/Sleeper.
- **Some model outliers to investigate** before treating the draft
  board as gospel — see the `adp_delta` column and the notes in the
  project memory.
