from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DAILY_DIR = DATA_DIR / "raw" / "daily"
RAW_CN_DAILY_DIR = DATA_DIR / "raw" / "cn_daily"
RAW_HK_DAILY_DIR = DATA_DIR / "raw" / "hk_daily"
PROCESSED_DIR = DATA_DIR / "processed"
RANKING_CACHE_DIR = PROCESSED_DIR / "rankings"
FUNDAMENTAL_DIR = DATA_DIR / "fundamental"
EARNINGS_CALENDAR_FILE = FUNDAMENTAL_DIR / "earnings_calendar.csv"
COMPANY_PROFILES_FILE = FUNDAMENTAL_DIR / "company_profiles.csv"
OPTIONABLE_TICKERS_FILE = FUNDAMENTAL_DIR / "optionable_tickers.csv"
A_SHARE_SUBTYPE_LEADERS_FILE = FUNDAMENTAL_DIR / "a_share_subtype_leaders.csv"
CONFIG_DIR = PROJECT_ROOT / "config"
NASDAQ100_FILE = CONFIG_DIR / "nasdaq100_tickers.txt"
NASDAQ100_OPTIONABLE_FILE = CONFIG_DIR / "nasdaq100_optionable_tickers.txt"
STOCK_PROFILES_FILE = CONFIG_DIR / "stock_profiles.csv"
STOCK_SUBTYPES_FILE = CONFIG_DIR / "stock_subtypes.csv"
CN_STOCK_POOL_FILE = CONFIG_DIR / "cn_stock_pool.csv"
HK_STOCK_POOL_FILE = CONFIG_DIR / "hk_stock_pool.csv"

DEFAULT_BENCHMARK = "QQQ"
CN_DEFAULT_BENCHMARK = "000905"
HK_DEFAULT_BENCHMARK = "HSTECH"
MIN_WINDOW = 2
MAX_WINDOW = 60
