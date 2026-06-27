export type RankingRow = {
  rank: number;
  ticker: string;
  type: string;
  has_options: "Y" | "N" | "U";
  sector: string;
  stock_type: string;
  earnings_date: string;
  date: string;
  close: number;
  latest_ma: number | null;
  ma_center: number;
  atr: number;
  atr_score: number;
  price_vs_center_pct: number;
  price_change_3d_pct: number | null;
  excess_atr_vs_benchmark: number;
  previous_rank_1: number | null;
  previous_rank_2: number | null;
  rank_change: number | null;
  rank_history: Array<{ date: string; rank: number | null }>;
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

export type RankingAlertItem = {
  ticker: string;
  rank: number;
  previous_rank: number | null;
  rank_change: number | null;
  avg_rank_5: number | null;
  best_rank_5: number | null;
  worst_rank_5: number | null;
};

export type RankingAlerts = {
  window: number;
  benchmark: string;
  as_of_date: string;
  previous_date: string;
  dates: string[];
  top_n: number;
  move_threshold: number;
  stable_top20: RankingAlertItem[];
  upward_moves: RankingAlertItem[];
  downward_moves: RankingAlertItem[];
  entered_top20: RankingAlertItem[];
  dropped_top20: RankingAlertItem[];
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

export type CompanyProfile = {
  ticker: string;
  name: string;
  market: string;
  exchange: string;
  locale: string;
  primary_exchange: string;
  currency_name: string;
  market_cap: string;
  sic_description: string;
  homepage_url: string;
  description: string;
  summary_zh: string;
  source: string;
  updated_at: string;
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

export function fetchRankingAlerts(window: number, asOfDate = "") {
  const params = new URLSearchParams({
    window: String(window),
    benchmark: "QQQ",
    days: "5",
    top_n: "20",
    move_threshold: "10"
  });
  if (asOfDate) {
    params.set("as_of_date", asOfDate);
  }
  return requestJson<RankingAlerts>(`/api/rankings/alerts?${params}`);
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

export function fetchStockProfile(ticker: string) {
  return requestJson<CompanyProfile>(`/api/stocks/${encodeURIComponent(ticker)}/profile`);
}
