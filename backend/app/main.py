from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.daily_briefs import router as daily_briefs_router
from app.api.earnings_reports import router as earnings_reports_router
from app.api.corporate_actions import router as corporate_actions_router
from app.api.industry_flows import router as industry_flows_router
from app.api.rankings import router as rankings_router
from app.api.stocks import router as stocks_router
from app.core.config import DAILY_BRIEF_OUTPUT_DIR, EARNINGS_SENTIMENT_REPORT_DIR


app = FastAPI(title="US Stock Ranking API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rankings_router)
app.include_router(stocks_router)
app.include_router(industry_flows_router)
app.include_router(daily_briefs_router)
app.include_router(earnings_reports_router)
app.include_router(corporate_actions_router)
DAILY_BRIEF_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/daily-briefs/files", StaticFiles(directory=DAILY_BRIEF_OUTPUT_DIR, html=True), name="daily-brief-files")
EARNINGS_SENTIMENT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/earnings-reports/files", StaticFiles(directory=EARNINGS_SENTIMENT_REPORT_DIR, html=True), name="earnings-report-files")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
