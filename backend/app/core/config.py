from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DAILY_DIR = DATA_DIR / "raw" / "daily"
CONFIG_DIR = PROJECT_ROOT / "config"
NASDAQ100_FILE = CONFIG_DIR / "nasdaq100_tickers.txt"
NASDAQ100_OPTIONABLE_FILE = CONFIG_DIR / "nasdaq100_optionable_tickers.txt"
STOCK_PROFILES_FILE = CONFIG_DIR / "stock_profiles.csv"

DEFAULT_BENCHMARK = "QQQ"
MIN_WINDOW = 2
MAX_WINDOW = 60
