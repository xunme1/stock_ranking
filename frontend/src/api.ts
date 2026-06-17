export type RankingRow = {
  rank: number;
  ticker: string;
  type: string;
  date: string;
  close: number;
  latest_ma: number | null;
  ma_center: number;
  atr: number;
  atr_score: number;
  price_vs_center_pct: number;
  excess_atr_vs_benchmark: number;
};

export type RankingResponse = {
  window: number;
  as_of_date: string;
  benchmark: string;
  benchmark_rank: number;
  benchmark_score: number;
  count: number;
  skipped: string[];
  data: RankingRow[];
};

export type DailyBar = {
  ticker: string;
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
};

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

async function requestJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function fetchRanking(window: number, asOfDate: string, applyAnnouncedRebalance: boolean) {
  const params = new URLSearchParams({
    window: String(window),
    benchmark: "QQQ",
    apply_announced_rebalance: String(applyAnnouncedRebalance)
  });
  if (asOfDate) {
    params.set("as_of_date", asOfDate);
  }
  return requestJson<RankingResponse>(`/api/rankings/latest?${params}`);
}

export function fetchRankingDates(limit = 260) {
  return requestJson<{ benchmark: string; count: number; dates: string[] }>(`/api/rankings/dates?limit=${limit}`);
}

export function fetchDailyBars(ticker: string, limit = 260, asOfDate = "") {
  const params = new URLSearchParams({ limit: String(limit) });
  if (asOfDate) {
    params.set("as_of_date", asOfDate);
  }
  return requestJson<{ ticker: string; count: number; data: DailyBar[] }>(
    `/api/stocks/${encodeURIComponent(ticker)}/daily?${params}`
  );
}
