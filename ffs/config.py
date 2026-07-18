from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"


def weekly_raw_path(season: int) -> Path:
    return RAW_DIR / "weekly" / f"{season}.parquet"


def weekly_scored_path(season: int, scoring_name: str) -> Path:
    return PROCESSED_DIR / "weekly" / scoring_name / f"{season}.parquet"


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
