export type RankingRow = {
  rank: number;
  ticker: string;
  name: string;
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
  market: Market;
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
  name: string;
  rank: number;
  previous_rank: number | null;
  rank_change: number | null;
  daily_change_pct: number | null;
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

export type AShareLeader = {
  sub_type: string;
  sub_type_cn: string;
  a_share_keywords: string;
  rank: number;
  code: string;
  name: string;
  market_cap_cny: string;
  market_cap_100m_cny: string;
  latest_price: string;
  change_pct: string;
  industry_boards: string;
  concept_boards: string;
};

export type StockPeers = {
  ticker: string;
  sub_type: string;
  sub_type_cn: string;
  a_share_keywords: string;
  source: string;
  a_share_leaders: AShareLeader[];
};

export type IndustryFlowRow = {
  rank: number;
  market: Market;
  trade_date: string;
  industry_name: string;
  flow_amount: number;
  stock_count: number;
  positive_count: number;
  negative_count: number;
};

export type IndustryFlowRanking = {
  market: Market;
  trade_date: string;
  count: number;
  data: IndustryFlowRow[];
};

export type IndustryFlowTrendPoint = {
  date: string;
  flow_amount: number;
};

export type IndustryFlowTrendSeries = {
  industry_name: string;
  points: IndustryFlowTrendPoint[];
};

export type IndustryFlowTrend = {
  market: Market;
  industries: string[];
  series: IndustryFlowTrendSeries[];
};

export type IndustryStockFlowRow = {
  rank: number;
  ticker: string;
  ths_code: string;
  name: string;
  industry_name: string;
  flow_amount: number;
};

export type IndustryStockFlowRanking = {
  market: Market;
  trade_date: string;
  industry_name: string;
  count: number;
  data: IndustryStockFlowRow[];
};

export type DailyBriefReport = {
  market: Market;
  market_label: string;
  date: string;
  window: number;
  filename: string;
  url: string;
  size_bytes: number;
  updated_at: number;
};

export type DailyBriefList = {
  count: number;
  dates: string[];
  data: DailyBriefReport[];
};

const API_BASE = import.meta.env.VITE_API_BASE ?? "";
export type Market = "us" | "cn" | "hk";

function benchmarkForMarket(market: Market) {
  if (market === "cn") return "000905";
  if (market === "hk") return "HSTECH";
  return "QQQ";
}

async function requestJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function fetchRanking(window: number, asOfDate: string, applyAnnouncedRebalance: boolean, market: Market = "us") {
  const params = new URLSearchParams({
    window: String(window),
    benchmark: benchmarkForMarket(market),
    market,
    apply_announced_rebalance: String(applyAnnouncedRebalance)
  });
  if (asOfDate) {
    params.set("as_of_date", asOfDate);
  }
  return requestJson<RankingResponse>(`/api/rankings/latest?${params}`);
}

export function fetchRankingDates(limit = 260, market: Market = "us") {
  const params = new URLSearchParams({
    limit: String(limit),
    benchmark: benchmarkForMarket(market),
    market
  });
  return requestJson<{ benchmark: string; market: Market; count: number; dates: string[] }>(`/api/rankings/dates?${params}`);
}

export function fetchRankingAlerts(window: number, asOfDate = "", market: Market = "us") {
  const params = new URLSearchParams({
    window: String(window),
    benchmark: benchmarkForMarket(market),
    market,
    days: "5",
    top_n: "20",
    move_threshold: "10"
  });
  if (asOfDate) {
    params.set("as_of_date", asOfDate);
  }
  return requestJson<RankingAlerts>(`/api/rankings/alerts?${params}`);
}

export function fetchDailyBars(ticker: string, limit = 260, asOfDate = "", market: Market = "us") {
  const params = new URLSearchParams({ limit: String(limit), market });
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

export function fetchStockPeers(ticker: string) {
  return requestJson<StockPeers>(`/api/stocks/${encodeURIComponent(ticker)}/peers`);
}

export function fetchIndustryFlowDates(limit = 260, market: Market = "us") {
  const params = new URLSearchParams({ limit: String(limit), market });
  return requestJson<{ market: Market; count: number; dates: string[] }>(`/api/industry-flows/dates?${params}`);
}

export function fetchIndustryFlowRanking(market: Market = "us", tradeDate = "", limit = 120) {
  const params = new URLSearchParams({ market, limit: String(limit) });
  if (tradeDate) {
    params.set("trade_date", tradeDate);
  }
  return requestJson<IndustryFlowRanking>(`/api/industry-flows/rankings?${params}`);
}

export function fetchIndustryFlowTrend(market: Market = "us", industries: string[] = [], topN = 8) {
  const params = new URLSearchParams({ market, top_n: String(topN) });
  if (industries.length) {
    params.set("industries", industries.join(","));
  }
  return requestJson<IndustryFlowTrend>(`/api/industry-flows/trend?${params}`);
}

export function fetchIndustryStockFlows(market: Market, industryName: string, tradeDate = "", limit = 300) {
  const params = new URLSearchParams({ market, limit: String(limit) });
  if (tradeDate) {
    params.set("trade_date", tradeDate);
  }
  return requestJson<IndustryStockFlowRanking>(
    `/api/industry-flows/${encodeURIComponent(industryName)}/stocks?${params}`
  );
}

export function fetchDailyBriefs() {
  return requestJson<DailyBriefList>("/api/daily-briefs");
}
