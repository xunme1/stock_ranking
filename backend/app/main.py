from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.rankings import router as rankings_router
from app.api.stocks import router as stocks_router


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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
