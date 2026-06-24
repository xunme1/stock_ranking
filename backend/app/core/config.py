from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DAILY_DIR = DATA_DIR / "raw" / "daily"
PROCESSED_DIR = DATA_DIR / "processed"
RANKING_CACHE_DIR = PROCESSED_DIR / "rankings"
FUNDAMENTAL_DIR = DATA_DIR / "fundamental"
EARNINGS_CALENDAR_FILE = FUNDAMENTAL_DIR / "earnings_calendar.csv"
COMPANY_PROFILES_FILE = FUNDAMENTAL_DIR / "company_profiles.csv"
CONFIG_DIR = PROJECT_ROOT / "config"
NASDAQ100_FILE = CONFIG_DIR / "nasdaq100_tickers.txt"
NASDAQ100_OPTIONABLE_FILE = CONFIG_DIR / "nasdaq100_optionable_tickers.txt"
STOCK_PROFILES_FILE = CONFIG_DIR / "stock_profiles.csv"

DEFAULT_BENCHMARK = "QQQ"
MIN_WINDOW = 2
MAX_WINDOW = 60
