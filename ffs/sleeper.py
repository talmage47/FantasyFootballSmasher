from __future__ import annotations

import json
from pathlib import Path

import requests

from ffs import config

API_BASE = "https://api.sleeper.app/v1"
_PLAYERS_MAX_AGE_DAYS = 7


def _get_json(url: str) -> dict | list:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_league(league_id: str) -> dict:
    return _get_json(f"{API_BASE}/league/{league_id}")


def fetch_rosters(league_id: str) -> list[dict]:
    return _get_json(f"{API_BASE}/league/{league_id}/rosters")


def fetch_users(league_id: str) -> list[dict]:
    return _get_json(f"{API_BASE}/league/{league_id}/users")


def fetch_players() -> dict[str, dict]:
    """The full NFL player map. ~5MB — cache aggressively."""
    return _get_json(f"{API_BASE}/players/nfl")


def load_or_fetch_players(force: bool = False) -> dict[str, dict]:
    """Return the cached player map, refetching if missing or older than a week."""
    path = config.sleeper_players_path()
    if not force and path.exists():
        import time
        age_days = (time.time() - path.stat().st_mtime) / 86400
        if age_days < _PLAYERS_MAX_AGE_DAYS:
            return json.loads(path.read_text())
    players = fetch_players()
    config.ensure_parent(path)
    path.write_text(json.dumps(players))
    return players


def save_league_snapshot(
    league_id: str,
    league: dict,
    rosters: list[dict],
    users: list[dict],
) -> Path:
    """Write league metadata, rosters, and users to data/raw/sleeper/<league_id>/."""
    d = config.sleeper_league_dir(league_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "league.json").write_text(json.dumps(league, indent=2))
    (d / "rosters.json").write_text(json.dumps(rosters, indent=2))
    (d / "users.json").write_text(json.dumps(users, indent=2))
    return d


def load_league_snapshot(league_id: str) -> tuple[dict, list[dict], list[dict]]:
    d = config.sleeper_league_dir(league_id)
    league = json.loads((d / "league.json").read_text())
    rosters = json.loads((d / "rosters.json").read_text())
    users = json.loads((d / "users.json").read_text())
    return league, rosters, users


def user_roster(
    league_id: str, username: str
) -> tuple[dict, list[str]]:
    """Return (user_meta, sleeper_player_ids) for the given username in the league."""
    _, rosters, users = load_league_snapshot(league_id)
    matches = [u for u in users if u.get("display_name", "").lower() == username.lower()]
    if not matches:
        available = ", ".join(u.get("display_name", "?") for u in users)
        raise ValueError(f"No user {username!r} in league {league_id}. Available: {available}")
    user = matches[0]
    owner_id = user["user_id"]
    roster = next((r for r in rosters if r.get("owner_id") == owner_id), None)
    if roster is None:
        raise ValueError(f"User {username} has no roster in league {league_id}")
    return user, roster.get("players") or []


def resolve_player_names(
    sleeper_ids: list[str], players_map: dict[str, dict]
) -> list[str]:
    """Convert Sleeper player_ids to display names our lineup matcher understands.

    DSTs in Sleeper are keyed by team abbreviation (e.g. "BUF"); we translate
    those to the "<Nickname> DST" format that our scored DST rows use.
    """
    from ffs.dst import TEAM_NICKNAMES

    names: list[str] = []
    for pid in sleeper_ids:
        if pid in TEAM_NICKNAMES:
            names.append(f"{TEAM_NICKNAMES[pid]} DST")
            continue
        p = players_map.get(pid)
        if p is None:
            names.append(pid)  # unknown — let downstream matcher flag it
            continue
        full = p.get("full_name") or (
            f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        )
        names.append(full or pid)
    return names
