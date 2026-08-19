# FantasyFootballSmasher (ffs)

A personal-use CLI that ingests NFL data, projects fantasy points, and
produces draft boards and weekly lineup recommendations. Designed for a
12-team, standard-scoring, redraft league with a 1QB / 2RB / 2WR / 1TE /
1FLEX starting lineup; the defaults can be overridden where it matters.

## What it does

**Data pipeline** (all files under `data/`, gitignored):
- Weekly player stats (`data/raw/weekly/<season>.parquet`) via
  [`nflreadpy`](https://nflreadpy.nflverse.com/) — one file per season.
- Per-team weekly stats (`data/raw/team_stats/<season>.parquet`) — the
  source for DST scoring (aggregated defensive and special-teams stats).
- Schedules (`data/raw/schedules/<season>.parquet`) — includes Vegas
  `spread_line` and `total_line`. Also joined against team stats to
  derive DST points-allowed bucket bonuses.
- Rosters (`data/raw/rosters/<season>.parquet`) — the authoritative
  current-team lookup for offseason moves.
- Depth charts (`data/raw/depth_charts/<season>.parquet`) — full
  snapshot history; latest snapshot per player is used to filter out
  backups.
- ADP (`data/raw/adp.parquet`) — FantasyPros redraft-overall ECR joined
  to `gsis_id` via `load_ff_playerids`.
- FFC ADP (`data/raw/ffc_adp.parquet`) — Fantasy Football Calculator
  ADP from real 12-team mock drafts, updated daily. Used as a second
  market source alongside FantasyPros; also drives rookie projection
  interpolation because FFC reflects actual draft behavior.
- Sleeper league snapshot (`data/raw/sleeper/<league_id>/`) — league
  settings, rosters, users, and cached global players.json. Underpins
  `--league-id` roster loading and `ffs draft-live`.

**Scoring:**
- `ffs/scoring.py` defines rules as a dict of `{stat_column: multiplier}`.
  `STANDARD` matches nflreadpy's built-in `fantasy_points` for a spot
  check (Josh Allen 2025 wk 1 = 38.76 in both). Includes ESPN kicker
  weights (tiered FG points + PATs).
- `ffs/dst.py` scores team defenses: base points from sacks, INTs,
  fumble recoveries, def/ST TDs, safeties, and blocked kicks, plus a
  bucketed points-allowed bonus (10 for shutout, sliding down to -5
  for 46+ allowed).
- Player-scored data lands in `data/processed/weekly/<ruleset>/<season>.parquet`;
  DST-scored data lands in `data/processed/dst/<ruleset>/<season>.parquet`.
  `career.load_scored` transparently concatenates both.

**Analytical layers:**
- `career` — cross-season aggregation and rolling per-player views.
- `matchups` — per-game fantasy points allowed by each defense to each
  position, ranked and league-relative.
- `sos` — strength of schedule per team, using any season's schedule
  and any (prior) season's defensive rankings.
- `projections` — baselines × opponent adjustment × game-environment factor.
  Per-week projections use a rolling last-N-game PPG (recent form); season
  projections use a weighted blend of the last 3 seasons (60/30/10, most
  recent first) so career-year outliers regress. Game-environment factor
  scales by team implied points (from Vegas `total_line` + `spread_line`)
  vs. the season's league mean — high-total games boost QB/RB/WR/TE/K.
  DST is excluded (offensive-environment factor doesn't apply cleanly).
  Roster override for offseason moves; depth chart filter to exclude backups;
  recency filter to drop retired players. Optional injury multiplier during
  the regular season.
- `draft` — value-based drafting (VBD) with configurable league size,
  optionally enriched with market ADP so you can spot values vs reaches, and
  rookies interpolated in from the ADP file when a `gsis_id` can't be joined.
  Supports arbitrary FLEX types (plain FLEX, WRRB_FLEX, REC_FLEX, SUPER_FLEX);
  SUPER_FLEX slots weight replacement demand heavily to QB, which correctly
  pushes elite QBs up ~10 spots on the board in superflex leagues.
- `lineup` — greedy optimal starter selection from a roster of player
  names, given weekly projections.
- `platoon` — for a chosen roster slot, ranks unrostered candidates by
  the extra season points you'd gain by starting whichever of anchor /
  candidate is projected higher each week. Bye-week coverage and the
  count of weeks the candidate would outproject the anchor are surfaced
  so you can identify true schedule complements (rather than just
  second-best-at-position).
- `draftlive` — live draft assistant. Polls Sleeper's draft-picks
  endpoint, maintains your roster and the remaining pool in memory,
  and renders a `rich`-powered dashboard that scores available
  candidates against your current roster (VBD adjusted for positional
  need + urgency from ADP-implied wait cost). Auto-imports league
  roster config (SUPER_FLEX / extra FLEX) from the cached Sleeper
  league snapshot.
- `durability` — historical injury frequency per player, computed from
  cached weekly injury reports (Out designations) combined with a
  scored-games gap fallback for long-term IR cases. Surfaced as a
  `games_missed_pct` column and an `injury_prone` flag on the draft
  board and `draft-live` dashboard; **does not** modify projections or
  rankings — market ADP has already partly priced this in, and risk
  tolerance is a personal choice.

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
uv run ffs fetch-team-stats               # per-team stats (source of DST scoring)
uv run ffs fetch-schedules                # schedules for the same range
uv run ffs fetch-schedules --season 2026  # + upcoming season's schedule
uv run ffs fetch-rosters --season 2026    # current-team assignments
uv run ffs fetch-depth-charts --season 2026  # starter / backup ordering
uv run ffs fetch-injuries                 # weekly injury reports
uv run ffs fetch-adp                      # FantasyPros consensus rankings
uv run ffs fetch-ffc-adp                  # Fantasy Football Calculator ADP (real mock drafts)
uv run ffs score                          # compute standard fantasy points (players + DST)
```

Total data footprint: ~20 MB.

## Command reference

Every command supports `--help` for full options.

### Ingest

| Command | Purpose |
|---|---|
| `ffs fetch [--season Y \| --start Y --end Y] [--force]` | Weekly stats. Defaults to `DEFAULT_SEASONS` (2016–2025). |
| `ffs fetch-schedules ...` | Season schedules. Same flags. |
| `ffs fetch-team-stats ...` | Per-team weekly stats (source for DST scoring). |
| `ffs fetch-injuries ...` | Weekly NFL injury reports (Out / Doubtful / Questionable). |
| `ffs fetch-rosters ...` | Annual rosters. |
| `ffs fetch-depth-charts ...` | Depth charts (all snapshots preserved). |
| `ffs fetch-adp [--force]` | FantasyPros redraft-overall ECR, no season needed. |
| `ffs fetch-ffc-adp [--scoring standard\|half_ppr\|ppr] [--teams N] [--year Y] [--force]` | Fantasy Football Calculator ADP from real mock drafts, refreshed daily. Used as a second market signal and to interpolate rookie projections. |
| `ffs fetch-sleeper-league --league-id ID [--username NAME]` | Cache Sleeper league snapshot (settings, rosters, users, players map). Optionally preview one user's roster. Enables `--league-id` roster loading and roster-spec auto-import for `draft` / `lineup` / `draft-live`. |

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
| `ffs defense --season Y --position P [--last-n N] [--sort easiest\|hardest]` | Ranks all 32 defenses by fantasy points allowed to a given position. Also surfaces `rushing_yds_allowed_pg` and `passing_yds_allowed_pg` so the raw yardage drivers behind the fantasy-points-allowed number are visible. |
| `ffs sos --schedule-season Y --position P [--rankings-season Y2] [--start-week --end-week]` | Team-level strength of schedule vs position. `rankings-season` defaults to `schedule-season − 1`. |

### Projections and draft

| Command | Purpose |
|---|---|
| `ffs project --season Y --week W [--position P] [--window 8] [--top 25]` | Per-week projections: baseline PPG × opponent adjustment. |
| `ffs project-season --season Y [--position P] [--window 17] [--top 40]` | Full-season projections (sums weekly projections). Includes a `bye_week` column. |
| `ffs schedule-player --season Y --player NAME` | Week-by-week matchup grid for one player: opponent, opp_factor, game_env_factor, week_projection. |
| `ffs draft --season Y [--teams 12] [--top 100] [--position P] [--after-pick N] [--sleepers \| --reaches] [--exclude-out] [--roster-slots ...] [--league-id ID] [--ruleset standard\|half_ppr\|ppr]` | VBD-ranked draft board across all positions, enriched with FantasyPros + FFC ADP when present. Includes `tier` (per-position VBD-gap clusters), `bye_week`, and durability columns (`games_missed_pct`, `injury_prone` flag when ≥20% games missed in recent seasons). `--after-pick`, `--sleepers`, `--reaches` require ADP. `--exclude-out` drops currently-Out players. `--roster-slots QB=1,RB=2,WR=2,TE=1,FLEX=2,SUPER_FLEX=1,K=1,DST=1` overrides starters (SUPER_FLEX, WRRB_FLEX, REC_FLEX all supported). `--league-id ID` auto-imports the starter/flex spec from a cached Sleeper league (see `fetch-sleeper-league`) — no need to type `--roster-slots` for your own league. |
| `ffs lineup --season Y --week W (--roster ROSTER.txt \| --league-id ID --username NAME) [--window 8] [--roster-slots ...] [--ruleset ...]` | Optimal starting lineup. Roster comes from a text file OR a cached Sleeper league snapshot. When `--league-id` is used, starter spec (SUPER_FLEX etc.) auto-imports from the league unless `--roster-slots` overrides. |
| `ffs platoon --season Y --slot {RB\|WR\|TE\|FLEX} (--roster ROSTER.txt \| --league-id ID --username NAME) [--top 20] [--show-grid] [--ruleset ...]` | Rank unrostered players by the season points they add as a week-to-week platoon partner for your best roster player at `--slot`. `--show-grid` prints the week-by-week matchup grid for the anchor + top candidate. |
| `ffs draft-live --league-id ID --username NAME [--season 2026] [--draft-id ID] [--favorite-team SF] [--poll 3] [--top 5] [--slot N]` | Live-updating draft assistant. Polls Sleeper's draft-picks endpoint every N seconds and renders a `rich` dashboard: draft state, your team, best available by position, top-N candidates scored against your current roster (VBD × need-multiplier + urgency from `wait_cost`), and an optional `--favorite-team` watch panel. Auto-detects your league's roster spec (including SUPER_FLEX) and your draft slot. K/DST are locked out of the top-N until round 8. |

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
bullish than the model. On draft day, `--after-pick N` narrows the
board to "best available at pick N", and `--sleepers` / `--reaches`
sort by `adp_delta` (sign-scoped, filtered to draftable players) to
surface value / avoid overpays. The `tier` column marks per-position
VBD-gap clusters so you can see when a tier is about to run out.

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

### Live-draft day

`ffs draft-live` is meant to run in a terminal alongside the Sleeper
app on your phone or in a browser. It polls the Sleeper draft-picks
endpoint every few seconds, maintains your roster in memory, and
updates a `rich` dashboard in place — no re-running between picks.

```bash
# One-time (or refresh) — cache the league snapshot so roster config
# (SUPER_FLEX etc.) and users can be resolved offline.
uv run ffs fetch-sleeper-league --league-id 123456789 --username tal

# Start the live assistant right before your draft.
uv run ffs draft-live --league-id 123456789 --username tal --favorite-team SF
```

The dashboard has four panels (five with `--favorite-team`):
draft state (round/pick/who's on the clock + last three picks), your
team (one row per starter slot with bye weeks visible), best available
by position, and top-N for you (sorted by `fit_score = vbd ×
need_multiplier + urgency`). The last column of the top-N table is a
short template explanation like "tier cliff (−28 VBD if you wait);
fills WR starter need; W7 bye stacks 2 starters". K and DST are hidden
from the top-N until round 8 so they don't clutter middle rounds. A
`miss%` column shows historical durability from `ffs/durability.py`
(computed from injury reports over recent seasons) — players at or
above 20% missed games are colored red and get an "injury-prone"
phrase appended to their explanation. Durability is informational
only; it does not shift fit_score or move players on the board.

Roster spec (starters, extra FLEX, SUPER_FLEX, etc.) is imported
automatically from Sleeper. If your draft slot hasn't been assigned in
Sleeper yet, pass `--slot N` to override until it is.

### Platoon / streaming (draft & bench planning)

Complementary players you can rotate week-to-week. If your RB1's
schedule is soft weeks 1/3/5 and tough weeks 2/4, `ffs platoon` finds
bench candidates whose schedule is the opposite — so the *max* of
anchor and candidate each week adds real season points on top of the
anchor's own total.

```bash
# See how your top RB's season plays out week by week
uv run ffs schedule-player --season 2026 --player "Bijan Robinson"

# Best RB platoon partner for the top RB on my roster (draft or bench-picking)
uv run ffs platoon --season 2026 --roster my_roster.txt --slot RB --top 20

# Same but with a Sleeper league instead of a text file, plus the head-to-head grid
uv run ffs platoon --season 2026 --league-id 123 --username tal --slot FLEX --show-grid
```

`platoon_points_added` is the total season points you'd gain by
starting whichever of anchor / candidate projects higher each week
(the anchor by itself is the baseline). `bye_covered = True` means the
candidate plays on your anchor's bye. `weeks_candidate_starts` is how
often the candidate beats the anchor — a candidate with only 2 starts
but +30 points is a bye-week + tough-matchup specialist, whereas one
with 8+ starts is more of a true co-#1.

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
  scoring.py      # ScoringRules dataclass + STANDARD / half_ppr / ppr rulesets
  dst.py          # score_dst — team-defense scoring from per-team weekly stats
  career.py       # load_scored, rolling views, career aggregates
  matchups.py     # points_allowed_by_game, defense_ranking, yards_allowed_by_game
  sos.py          # opponents_by_team, team_sos
  injuries.py     # latest_injuries_per_player, availability_factor
  projections.py  # player_baseline, project_week, project_weekly, project_season
  draft.py        # replacement_ranks, draft_rankings, with_adp, FLEX/SUPER_FLEX
  lineup.py       # resolve_roster, optimize_lineup
  platoon.py      # platoon_value, platoon_grid
  draftlive.py    # snake picks, positional_need, wait_cost, score_candidates
  durability.py   # player_durability — historical injury-prone signal
  sleeper.py      # Sleeper API client + league/draft snapshot loaders
  cli.py          # typer app (all commands live here)
```

Every module is a plain function or dataclass over Pandas DataFrames.
No abstract base classes, no plugins, no ORM. Adding a new dataset or
scoring format is a new dict, not a new class hierarchy.

## Known limitations

- **K and DST projections skip opponent adjustment** — both use a flat
  `opp_factor = 1.0`. For K, defense-vs-K isn't a meaningful signal
  (game total / weather dominate). For DST, a smarter model would use
  the opposing offense's turnover and sack rates; today the projection
  is just the multi-season weighted baseline of the DST's own scoring.
  VBD also tends to over-rate both K and DST relative to how the
  market drafts them; treat their `adp_delta` values as noise.
- **Rookie projections are market-derived, not model-derived** — rookies
  have no NFL games so the baseline can't produce anything. `draft` merges
  unmatched FantasyPros entries and interpolates projected points from
  same-position veterans on the `(adp, projected_points)` curve. Rookies
  are flagged in the `is_rookie` column.
- **No opportunity model** — a player's baseline is their historical
  PPG, not a snap-share × team-context estimate. A backup who inherits
  a starting role won't have his projection change until games happen.
- **Variance / floor-ceiling now surfaced** — `floor` and `ceiling`
  columns on draft board and lineup are `projection ± σ`, where σ is
  the per-game std-dev of a player's last N games (multiplied by
  √games for season-level projections). This is a rough boom-bust
  hint, not a probability distribution.
- **Sleeper integration is read-only** — writes (setting your lineup,
  making picks, sending messages) are not supported. `ffs
  fetch-sleeper-league` caches league settings, rosters, users, and
  the player map. `draft`, `lineup`, and `draft-live` all accept
  `--league-id` and auto-import your league's starter/flex spec
  (including SUPER_FLEX, WRRB_FLEX, and REC_FLEX). League scoring
  rules (custom PPR fractions, TE-premium, etc.) are NOT yet imported
  — `--ruleset` still picks between standard/half_ppr/ppr manually.
- **Some model outliers to investigate** before treating the draft
  board as gospel — see the `adp_delta` column and the notes in the
  project memory.
