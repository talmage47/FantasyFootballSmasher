from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

DEFAULT_SEASONS: list[int] = list(range(2016, 2026))


def weekly_raw_path(season: int) -> Path:
    return RAW_DIR / "weekly" / f"{season}.parquet"


def schedules_path(season: int) -> Path:
    return RAW_DIR / "schedules" / f"{season}.parquet"


def rosters_path(season: int) -> Path:
    return RAW_DIR / "rosters" / f"{season}.parquet"


def depth_charts_path(season: int) -> Path:
    return RAW_DIR / "depth_charts" / f"{season}.parquet"


def adp_path() -> Path:
    return RAW_DIR / "adp.parquet"


def weekly_scored_path(season: int, scoring_name: str) -> Path:
    return PROCESSED_DIR / "weekly" / scoring_name / f"{season}.parquet"


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
