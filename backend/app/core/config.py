from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")
DATA_DIR = PROJECT_ROOT / "data"
RAW_DAILY_DIR = DATA_DIR / "raw" / "daily"
RAW_CN_DAILY_DIR = DATA_DIR / "raw" / "cn_daily"
RAW_HK_DAILY_DIR = DATA_DIR / "raw" / "hk_daily"
PROCESSED_DIR = DATA_DIR / "processed"
RANKING_CACHE_DIR = PROCESSED_DIR / "rankings"
INDUSTRY_FUND_FLOW_DB = PROCESSED_DIR / "industry_fund_flow.db"
CORPORATE_ACTION_NEWS_DB = PROCESSED_DIR / "corporate_action_news.db"
FUNDAMENTAL_DIR = DATA_DIR / "fundamental"
EARNINGS_CALENDAR_FILE = FUNDAMENTAL_DIR / "earnings_calendar.csv"
EARNINGS_CALENDAR_HISTORY_FILE = FUNDAMENTAL_DIR / "earnings_calendar_history.csv"
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
DAILY_BRIEF_OUTPUT_DIR = PROJECT_ROOT / "experiments" / "daily_brief" / "output"
EARNINGS_SENTIMENT_REPORT_DIR = DATA_DIR / "processed" / "earnings_sentiment_reports"

DEFAULT_BENCHMARK = "QQQ"
CN_DEFAULT_BENCHMARK = "000905"
HK_DEFAULT_BENCHMARK = "HSTECH"
MIN_WINDOW = 2
MAX_WINDOW = 60

# Authentication is enabled only when both settings are provided. Keeping
# this opt-in preserves local data-maintenance scripts while allowing deployed
# instances to require a login without embedding the password in source code.
AUTH_PASSWORD = os.getenv("STOCK_RANKING_PASSWORD", "")
AUTH_SESSION_SECRET = os.getenv("STOCK_RANKING_SESSION_SECRET", "")
AUTH_SESSION_HOURS = int(os.getenv("STOCK_RANKING_SESSION_HOURS", "12"))
AUTH_COOKIE_SECURE = os.getenv("STOCK_RANKING_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes"}
