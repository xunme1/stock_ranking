import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import {
  ArrowLeft,
  BarChart3,
  CalendarDays,
  Activity,
  ChevronLeft,
  ChevronRight,
  HelpCircle,
  RefreshCw,
  Search
} from "lucide-react";
import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type UTCTimestamp
} from "lightweight-charts";
import {
  fetchDailyBars,
  fetchRanking,
  fetchRankingAlerts,
  fetchRankingDates,
  fetchStockPeers,
  fetchStockProfile,
  type AShareLeader,
  type CompanyProfile,
  type DailyBar,
  type Market,
  type RankingAlertItem,
  type RankingAlerts,
  type RankingResponse,
  type RankingRow,
  type StockPeers
} from "./api";

const DEFAULT_WINDOW = 10;
const WINDOW_OPTIONS = [10, 20];
const APPLY_ANNOUNCED_REBALANCE = true;
const MARKET_OPTIONS: Array<{ value: Market; label: string; benchmark: string; title: string; eyebrow: string }> = [
  { value: "us", label: "美股", benchmark: "QQQ", title: "纳指成分股 ATR 排名", eyebrow: "Nasdaq-100 Relative Strength" },
  { value: "cn", label: "A股", benchmark: "000905", title: "A股股票池 ATR 排名", eyebrow: "CSI 500 Relative Strength" },
  { value: "hk", label: "港股", benchmark: "HSTECH", title: "港股股票池 ATR 排名", eyebrow: "Hang Seng TECH Relative Strength" }
];
const CHART_VISIBLE_DAYS = 20;
const PRICE_CHART_HEIGHT = 460;
const DETAIL_SUB_CHART_HEIGHT = 260;
const ALL_SECTORS = "全部";
const SECTOR_ORDER = [
  "科技",
  "通信传媒",
  "可选消费",
  "必选消费",
  "医疗健康",
  "工业",
  "公用事业",
  "能源",
  "材料",
  "金融",
  "房地产",
  "ETF",
  "其他"
];

const SECTOR_LABELS: Record<string, string> = {
  "Information Technology": "科技",
  "Communication Services": "通信传媒",
  "Consumer Discretionary": "可选消费",
  "Consumer Staples": "必选消费",
  "Health Care": "医疗健康",
  Industrials: "工业",
  Utilities: "公用事业",
  Energy: "能源",
  Materials: "材料",
  Financials: "金融",
  "Real Estate": "房地产",
  ETF: "ETF",
  Unknown: "其他"
};

type RouteState = {
  page: "dashboard" | "stock";
  ticker?: string;
  date?: string;
  market?: Market;
};

function numberText(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function volumeText(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  if (Math.abs(value) >= 1_000_000_000) return `${numberText(value / 1_000_000_000, 2)}B`;
  if (Math.abs(value) >= 1_000_000) return `${numberText(value / 1_000_000, 2)}M`;
  if (Math.abs(value) >= 1_000) return `${numberText(value / 1_000, 2)}K`;
  return numberText(value, 0);
}

function percentText(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${value >= 0 ? "+" : ""}${numberText(value, 2)}%`;
}

function sectorLabel(sector: string | null | undefined) {
  if (!sector) return "其他";
  return SECTOR_LABELS[sector] ?? sector;
}

function marketBenchmark(market: Market) {
  return MARKET_OPTIONS.find((item) => item.value === market)?.benchmark ?? "QQQ";
}

function sectorSortValue(label: string) {
  const index = SECTOR_ORDER.indexOf(label);
  return index === -1 ? SECTOR_ORDER.length : index;
}

function rankTrend(row: RankingRow) {
  if (row.rank_change === null || row.rank_change === undefined || row.rank_change === 0) {
    return { symbol: "－", className: "rankFlat", label: "排名持平" };
  }
  if (row.rank_change > 0) return { symbol: "↑", className: "rankUp", label: `排名提升 ${row.rank_change} 位` };
  return { symbol: "↓", className: "rankDown", label: `排名下降 ${Math.abs(row.rank_change)} 位` };
}

function rankTooltip(row: RankingRow) {
  return [
    `今日排名：${row.rank}`,
    `昨日排名：${row.previous_rank_1 ?? "--"}`,
    `前日排名：${row.previous_rank_2 ?? "--"}`
  ].join("\n");
}

function priorRank(row: RankingRow, daysAgo: number) {
  const history = [...(row.rank_history ?? [])].sort((a, b) => a.date.localeCompare(b.date));
  const item = history[history.length - 1 - daysAgo];
  return item?.rank ?? null;
}

function RankHistoryPopover({ row }: { row: RankingRow }) {
  const history = [...(row.rank_history ?? [])].sort((a, b) => a.date.localeCompare(b.date));
  const valid = history.filter((item) => item.rank !== null && item.rank !== undefined) as Array<{
    date: string;
    rank: number;
  }>;
  const width = 190;
  const height = 58;
  const padX = 10;
  const padY = 8;
  const minRank = valid.length ? Math.min(...valid.map((item) => item.rank)) : row.rank;
  const maxRank = valid.length ? Math.max(...valid.map((item) => item.rank)) : row.rank;
  const spread = Math.max(maxRank - minRank, 1);
  const points = valid.map((item, index) => {
    const x = valid.length <= 1 ? width / 2 : padX + (index / (valid.length - 1)) * (width - padX * 2);
    const y = padY + ((item.rank - minRank) / spread) * (height - padY * 2);
    return { ...item, x, y };
  });
  const polyline = points.map((point) => `${point.x},${point.y}`).join(" ");
  const anchors = [
    { label: "前1日", value: priorRank(row, 1) },
    { label: "前3日", value: priorRank(row, 3) },
    { label: "前5日", value: priorRank(row, 5) },
    { label: "前10日", value: priorRank(row, 10) }
  ];

  return (
    <div className="rankPopover">
      <div className="rankPopoverTop">
        <strong>{row.ticker} 近10日排名</strong>
        <span>今日 #{row.rank}</span>
      </div>
      <svg className="rankSparkline" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${row.ticker} 排名变化`}>
        <line x1={padX} y1={padY} x2={width - padX} y2={padY} />
        <line x1={padX} y1={height - padY} x2={width - padX} y2={height - padY} />
        {polyline ? <polyline points={polyline} /> : null}
        {points.map((point) => (
          <circle key={`${point.date}-${point.rank}`} cx={point.x} cy={point.y} r="3" />
        ))}
      </svg>
      <div className="rankAxisHints">
        <span>上方更好</span>
        <strong>最佳 #{minRank}</strong>
        <strong>最差 #{maxRank}</strong>
      </div>
      <div className="rankAnchorGrid">
        {anchors.map((anchor) => (
          <span key={anchor.label}>
            {anchor.label}
            <strong>{anchor.value ? `#${anchor.value}` : "--"}</strong>
          </span>
        ))}
      </div>
    </div>
  );
}

function RankingTrendChart({ row }: { row: RankingRow | undefined }) {
  const history = [...(row?.rank_history ?? [])].sort((a, b) => a.date.localeCompare(b.date));
  const valid = history.filter((item) => item.rank !== null && item.rank !== undefined) as Array<{
    date: string;
    rank: number;
  }>;
  const width = 720;
  const height = 260;
  const padLeft = 54;
  const padRight = 24;
  const padTop = 28;
  const padBottom = 42;
  const minRank = valid.length ? Math.min(...valid.map((item) => item.rank)) : 1;
  const maxRank = valid.length ? Math.max(...valid.map((item) => item.rank)) : 20;
  const spread = Math.max(maxRank - minRank, 1);
  const points = valid.map((item, index) => {
    const x = valid.length <= 1 ? width / 2 : padLeft + (index / (valid.length - 1)) * (width - padLeft - padRight);
    const y = padTop + ((item.rank - minRank) / spread) * (height - padTop - padBottom);
    return { ...item, x, y };
  });
  const line = points.map((point) => `${point.x},${point.y}`).join(" ");
  const area = points.length
    ? `${padLeft},${height - padBottom} ${line} ${width - padRight},${height - padBottom}`
    : "";
  const labels = points.filter((_, index) => index === 0 || index === points.length - 1 || index % 3 === 0);

  if (!row || !valid.length) {
    return <div className="rankingTrendEmpty">暂无排名历史数据</div>;
  }

  return (
    <svg className="rankingTrendChart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${row.ticker} 排名变化`}>
      <defs>
        <linearGradient id={`rankArea-${row.ticker}`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#1f6feb" stopOpacity="0.2" />
          <stop offset="100%" stopColor="#1f6feb" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <line className="trendGrid" x1={padLeft} x2={width - padRight} y1={padTop} y2={padTop} />
      <line className="trendGrid" x1={padLeft} x2={width - padRight} y1={height - padBottom} y2={height - padBottom} />
      <line className="trendAxis" x1={padLeft} x2={padLeft} y1={padTop} y2={height - padBottom} />
      <text className="trendAxisText" x={14} y={padTop + 4}>最佳 #{minRank}</text>
      <text className="trendAxisText" x={14} y={height - padBottom + 4}>最差 #{maxRank}</text>
      {area ? <polygon className="trendArea" points={area} fill={`url(#rankArea-${row.ticker})`} /> : null}
      {line ? <polyline className="trendLine" points={line} /> : null}
      {points.map((point) => (
        <g key={`${point.date}-${point.rank}`}>
          <circle className="trendDotHalo" cx={point.x} cy={point.y} r="7" />
          <circle className="trendDot" cx={point.x} cy={point.y} r="4" />
          <text className="trendDotLabel" x={point.x} y={point.y - 12}>#{point.rank}</text>
        </g>
      ))}
      {labels.map((point) => (
        <text key={`label-${point.date}`} className="trendDateLabel" x={point.x} y={height - 14}>
          {point.date.slice(5)}
        </text>
      ))}
    </svg>
  );
}

function RankingTrendCard({
  row,
  windowSize,
  loading,
  onWindowChange
}: {
  row: RankingRow | undefined;
  windowSize: number;
  loading: boolean;
  onWindowChange: (window: number) => void;
}) {
  const anchors = [1, 3, 5, 10].map((days) => ({ days, rank: row ? priorRank(row, days) : null }));
  const change = row?.rank_change ?? null;

  return (
    <section className="rankingTrendCard">
      <div className="panelHeader trendHeader">
        <div>
          <p className="eyebrow">Ranking Trend</p>
          <h2>排名变化</h2>
        </div>
        <div className="alertSwitch compactSwitch" aria-label="排名窗口">
          <span>窗口</span>
          {WINDOW_OPTIONS.map((value) => (
            <button
              key={value}
              type="button"
              className={windowSize === value ? "active" : ""}
              disabled={loading}
              onClick={() => onWindowChange(value)}
            >
              {value}日
            </button>
          ))}
        </div>
      </div>
      <div className="rankTrendSummary">
        <div>
          <span>当前排名</span>
          <strong>{row ? `#${row.rank}` : "--"}</strong>
        </div>
        <div>
          <span>较前日</span>
          <strong className={change !== null && change >= 0 ? "positive" : "negative"}>
            {change === null ? "--" : change > 0 ? `提升 ${change}` : change < 0 ? `下降 ${Math.abs(change)}` : "持平"}
          </strong>
        </div>
        <div>
          <span>ATR倍数</span>
          <strong className={row && row.atr_score >= 0 ? "positive" : "negative"}>{numberText(row?.atr_score, 3)}</strong>
        </div>
      </div>
      <RankingTrendChart row={row} />
      <div className="rankAnchorCards">
        {anchors.map((anchor) => (
          <div key={anchor.days}>
            <span>前{anchor.days}日</span>
            <strong>{anchor.rank ? `#${anchor.rank}` : "--"}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function toTimestamp(date: string) {
  return Math.floor(new Date(`${date}T00:00:00Z`).getTime() / 1000) as UTCTimestamp;
}

function timeKey(time: unknown) {
  if (typeof time === "number") return String(time);
  if (typeof time === "string") return String(toTimestamp(time));
  if (time && typeof time === "object" && "year" in time && "month" in time && "day" in time) {
    const item = time as { year: number; month: number; day: number };
    return String(toTimestamp(formatYmd(item.year, item.month - 1, item.day)));
  }
  return "";
}

function parseRoute(): RouteState {
  const match = window.location.pathname.match(/^\/stocks\/([A-Za-z0-9.-]+)$/);
  if (!match) return { page: "dashboard" };
  const marketParam = new URLSearchParams(window.location.search).get("market");
  return {
    page: "stock",
    ticker: match[1].toUpperCase(),
    date: new URLSearchParams(window.location.search).get("date") ?? "",
    market: (marketParam === "cn" || marketParam === "hk" ? marketParam : "us") as Market
  };
}

function navigateTo(url: string) {
  window.history.pushState({}, "", url);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function parseYmd(date: string) {
  const [year, month, day] = date.split("-").map(Number);
  return { year, monthIndex: month - 1, day };
}

function formatYmd(year: number, monthIndex: number, day: number) {
  return `${year}-${String(monthIndex + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function monthTitle(year: number, monthIndex: number) {
  return `${year}-${String(monthIndex + 1).padStart(2, "0")}`;
}

function movingAverageData(bars: DailyBar[], window: number) {
  const result: Array<{ time: UTCTimestamp; value: number }> = [];
  let sum = 0;
  bars.forEach((bar, index) => {
    sum += bar.close;
    if (index >= window) sum -= bars[index - window].close;
    if (index >= window - 1) {
      result.push({ time: toTimestamp(bar.date), value: sum / window });
    }
  });
  return result;
}

function latestMovingAverage(bars: DailyBar[], window: number) {
  if (bars.length < window) return null;
  const slice = bars.slice(-window);
  return slice.reduce((sum, bar) => sum + bar.close, 0) / window;
}

function trueRangeBars(bars: DailyBar[]) {
  return bars.map((bar, index) => {
    const previousClose = index > 0 ? bars[index - 1].close : bar.close;
    return Math.max(bar.high - bar.low, Math.abs(bar.high - previousClose), Math.abs(bar.low - previousClose));
  });
}

function latestAtr(bars: DailyBar[], window: number) {
  if (bars.length < window + 1) return null;
  const ranges = trueRangeBars(bars).slice(-window);
  return ranges.reduce((sum, value) => sum + value, 0) / window;
}

function periodReturn(bars: DailyBar[], window: number) {
  if (bars.length <= window) return null;
  const latest = bars[bars.length - 1];
  const previous = bars[bars.length - 1 - window];
  return (latest.close / previous.close - 1) * 100;
}

function relativeReturn(stockBars: DailyBar[], benchmarkBars: DailyBar[], window: number) {
  const benchmarkByDate = new Map(benchmarkBars.map((bar) => [bar.date, bar]));
  const alignedStockBars = stockBars.filter((bar) => benchmarkByDate.has(bar.date));
  if (alignedStockBars.length <= window) return null;
  const latestStock = alignedStockBars[alignedStockBars.length - 1];
  const previousStock = alignedStockBars[alignedStockBars.length - 1 - window];
  const latestBenchmark = benchmarkByDate.get(latestStock.date);
  const previousBenchmark = benchmarkByDate.get(previousStock.date);
  if (!latestBenchmark || !previousBenchmark) return null;
  return (latestStock.close / previousStock.close - 1) * 100 - (latestBenchmark.close / previousBenchmark.close - 1) * 100;
}

function TradingCalendar({
  value,
  availableDates,
  onChange
}: {
  value: string;
  availableDates: string[];
  onChange: (date: string) => void;
}) {
  const latestDate = availableDates.length ? availableDates[availableDates.length - 1] : "";
  const anchorDate = value || latestDate || new Date().toISOString().slice(0, 10);
  const parsedAnchor = parseYmd(anchorDate);
  const [open, setOpen] = useState(false);
  const [viewYear, setViewYear] = useState(parsedAnchor.year);
  const [viewMonth, setViewMonth] = useState(parsedAnchor.monthIndex);

  useEffect(() => {
    const parsed = parseYmd(anchorDate);
    setViewYear(parsed.year);
    setViewMonth(parsed.monthIndex);
  }, [anchorDate]);

  const availableSet = useMemo(() => new Set(availableDates), [availableDates]);
  const cells = useMemo(() => {
    const firstWeekday = new Date(Date.UTC(viewYear, viewMonth, 1)).getUTCDay();
    const daysInMonth = new Date(Date.UTC(viewYear, viewMonth + 1, 0)).getUTCDate();
    const result: Array<{ key: string; date: string; day: number | null; available: boolean }> = [];
    for (let i = 0; i < firstWeekday; i += 1) {
      result.push({ key: `empty-start-${i}`, date: "", day: null, available: false });
    }
    for (let day = 1; day <= daysInMonth; day += 1) {
      const date = formatYmd(viewYear, viewMonth, day);
      result.push({ key: date, date, day, available: availableSet.has(date) });
    }
    while (result.length % 7 !== 0) {
      result.push({ key: `empty-end-${result.length}`, date: "", day: null, available: false });
    }
    return result;
  }, [availableSet, viewMonth, viewYear]);

  const shiftMonth = (delta: number) => {
    const next = new Date(Date.UTC(viewYear, viewMonth + delta, 1));
    setViewYear(next.getUTCFullYear());
    setViewMonth(next.getUTCMonth());
  };

  const selectDate = (date: string) => {
    onChange(date);
    setOpen(false);
  };

  return (
    <div className="calendarControl">
      <button className="calendarTrigger" type="button" onClick={() => setOpen((current) => !current)}>
        <CalendarDays size={16} aria-hidden="true" />
        <span>收盘日期</span>
        <strong>{value || "最新"}</strong>
      </button>
      {open ? (
        <div className="calendarPopover">
          <div className="calendarTop">
            <button type="button" className="iconButton" onClick={() => shiftMonth(-1)} aria-label="上个月">
              <ChevronLeft size={16} aria-hidden="true" />
            </button>
            <strong>{monthTitle(viewYear, viewMonth)}</strong>
            <button type="button" className="iconButton" onClick={() => shiftMonth(1)} aria-label="下个月">
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          </div>
          <div className="calendarWeekdays">
            {["日", "一", "二", "三", "四", "五", "六"].map((label) => (
              <span key={label}>{label}</span>
            ))}
          </div>
          <div className="calendarGrid">
            {cells.map((cell) =>
              cell.day === null ? (
                <span key={cell.key} className="calendarBlank" />
              ) : (
                <button
                  key={cell.key}
                  type="button"
                  className={`calendarDay ${cell.available ? "" : "unavailable"} ${
                    cell.date === value ? "selected" : ""
                  }`}
                  disabled={!cell.available}
                  onClick={() => selectDate(cell.date)}
                  title={cell.available ? cell.date : `${cell.date} 无数据`}
                >
                  {cell.day}
                </button>
              )
            )}
          </div>
          <button
            type="button"
            className="calendarLatest"
            disabled={!latestDate}
            onClick={() => latestDate && selectDate(latestDate)}
          >
            最新交易日 {latestDate || "--"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function MiniChartPanel({ ticker, asOfDate, market }: { ticker: string; asOfDate: string; market: Market }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [bars, setBars] = useState<DailyBar[]>([]);

  useEffect(() => {
    let alive = true;
    fetchDailyBars(ticker, 120, asOfDate, market).then((result) => {
      if (alive) setBars(result.data);
    });
    return () => {
      alive = false;
    };
  }, [ticker, asOfDate, market]);

  useEffect(() => {
    if (!containerRef.current) return;
    containerRef.current.innerHTML = "";
    const chart = createChart(containerRef.current, baseChartOptions(420));
    const candleSeries = chart.addSeries(CandlestickSeries, candleStyle());
    const ma5 = chart.addSeries(LineSeries, { color: "#1f6feb", lineWidth: 2, title: "MA5" });
    const ma10 = chart.addSeries(LineSeries, { color: "#d27a00", lineWidth: 2, title: "MA10" });
    const ma20 = chart.addSeries(LineSeries, { color: "#6f42c1", lineWidth: 2, title: "MA20" });
    chartRef.current = chart;

    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    handleResize();
    window.addEventListener("resize", handleResize);

    candleSeries.setData(bars.map((bar) => ({ time: toTimestamp(bar.date), open: bar.open, high: bar.high, low: bar.low, close: bar.close })));
    ma5.setData(movingAverageData(bars, 5));
    ma10.setData(movingAverageData(bars, 10));
    ma20.setData(movingAverageData(bars, 20));
    chart.timeScale().fitContent();
    if (bars.length > CHART_VISIBLE_DAYS) {
      chart.timeScale().setVisibleLogicalRange({ from: bars.length - CHART_VISIBLE_DAYS, to: bars.length - 1 });
    }

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [bars]);

  return (
    <section className="detail" id="detail">
      <div className="detailHeader">
        <div>
          <p className="eyebrow">Ticker Detail</p>
          <h2>{ticker} 详情预览</h2>
        </div>
        <span className="statusText">默认显示最近 20 日</span>
      </div>
      <div className="legendLine">
        <span className="legendDot candle" /> K线
        <span className="legendDot ma5" /> MA5
        <span className="legendDot ma10" /> MA10
        <span className="legendDot ma20" /> MA20
      </div>
      <div className="chartShell" ref={containerRef} />
    </section>
  );
}

function alertRankText(item: RankingAlertItem) {
  if (item.previous_rank === null || item.previous_rank === undefined || item.rank_change === null) {
    return `#${item.rank}`;
  }
  const changeText =
    item.rank_change > 0 ? `↑${item.rank_change}` : item.rank_change < 0 ? `↓${Math.abs(item.rank_change)}` : "持平";
  return `#${item.rank} / 昨 #${item.previous_rank} / ${changeText}`;
}

function sortAlertItems(items: RankingAlertItem[], metric: "stable" | "move") {
  if (metric === "stable") {
    return [...items].sort((a, b) => {
      const avgA = a.avg_rank_5 ?? 999;
      const avgB = b.avg_rank_5 ?? 999;
      return avgA - avgB || a.rank - b.rank;
    });
  }
  return [...items].sort((a, b) => {
    const moveA = Math.abs(a.rank_change ?? 0);
    const moveB = Math.abs(b.rank_change ?? 0);
    const pctA = a.daily_change_pct ?? Number.NEGATIVE_INFINITY;
    const pctB = b.daily_change_pct ?? Number.NEGATIVE_INFINITY;
    return moveB - moveA || pctB - pctA || a.rank - b.rank;
  });
}

function AlertList({
  title,
  items,
  tone,
  metric,
  market
}: {
  title: string;
  items: RankingAlertItem[];
  tone?: "up" | "down" | "stable";
  metric: "stable" | "move";
  market: Market;
}) {
  const sortedItems = sortAlertItems(items, metric);
  const displayName = (item: RankingAlertItem) => {
    const name = String(item.name ?? "").trim();
    if (market === "us" || !name || name.toLowerCase() === "nan") return item.ticker;
    return name;
  };
  return (
    <section className="alertSection">
      <div className="alertSectionTitle">
        <h3>{title}</h3>
        <span>{items.length}</span>
      </div>
      {sortedItems.length ? (
        <div className="alertRows">
          {sortedItems.map((item) => (
            <div className="alertRow" key={`${title}-${item.ticker}`}>
              <strong title={item.ticker}>{displayName(item)}</strong>
              <span className={tone === "up" ? "positive" : tone === "down" ? "negative" : ""}>
                {metric === "stable"
                  ? `#${item.rank} / 均 ${numberText(item.avg_rank_5, 1)}`
                  : alertRankText(item)}
              </span>
              <em>
                {item.best_rank_5 && item.worst_rank_5 ? `5日 ${item.best_rank_5}-${item.worst_rank_5}` : "--"}
              </em>
            </div>
          ))}
        </div>
      ) : (
        <p className="emptyAlert">暂无</p>
      )}
    </section>
  );
}

function RankingAlertCard({
  alerts,
  market,
  activeWindow,
  loading,
  onWindowChange,
  onClose
}: {
  alerts: RankingAlerts;
  market: Market;
  activeWindow: number;
  loading: boolean;
  onWindowChange: (window: number) => void;
  onClose: () => void;
}) {
  return (
    <aside className="rankingAlertCard" role="dialog" aria-label="排名异常监测">
      <div className="alertHeader">
        <div>
          <p className="eyebrow">Ranking Monitor</p>
          <h2>排名稳定性与异常监测</h2>
        </div>
        <button className="iconButton" type="button" onClick={onClose} aria-label="关闭排名监测">
          ×
        </button>
      </div>
      <div className="alertSwitch" aria-label="监测窗口">
        <span>监测窗口</span>
        {WINDOW_OPTIONS.map((value) => (
          <button
            key={value}
            type="button"
            className={activeWindow === value ? "active" : ""}
            disabled={loading}
            onClick={() => onWindowChange(value)}
          >
            {value}日
          </button>
        ))}
      </div>
      <p className="alertIntro">
        窗口 {alerts.window}日 / 截止 {alerts.as_of_date}。监测最近5个交易日稳定前20，以及今日相对昨日排名变化超过10名的股票。
      </p>
      <div className="alertGrid">
        <AlertList title="近5日稳定前20" items={alerts.stable_top20} tone="stable" metric="stable" market={market} />
        <AlertList title="大幅上升" items={alerts.upward_moves} tone="up" metric="move" market={market} />
        <AlertList title="大幅下降" items={alerts.downward_moves} tone="down" metric="move" market={market} />
        <AlertList title="当日进入前20" items={alerts.entered_top20} tone="up" metric="move" market={market} />
        <AlertList title="当日跌出前20" items={alerts.dropped_top20} tone="down" metric="move" market={market} />
      </div>
    </aside>
  );
}

function baseChartOptions(height: number) {
  return {
    height,
    layout: {
      background: { color: "#ffffff" },
      textColor: "#18212f",
      fontFamily: "Inter, Segoe UI, Arial, sans-serif"
    },
    grid: {
      vertLines: { color: "#eef2f7" },
      horzLines: { color: "#eef2f7" }
    },
    rightPriceScale: { borderColor: "#d9e0ea", minimumWidth: 72 },
    timeScale: { borderColor: "#d9e0ea", timeVisible: false },
    crosshair: { mode: 1 }
  };
}

function candleStyle() {
  return {
    upColor: "#0f9f6e",
    downColor: "#d93d3d",
    borderUpColor: "#0f9f6e",
    borderDownColor: "#d93d3d",
    wickUpColor: "#0f9f6e",
    wickDownColor: "#d93d3d"
  };
}

function RankingTable({
  rows,
  benchmark,
  market,
  selectedTicker,
  onPreview,
  onOpen
}: {
  rows: RankingRow[];
  benchmark: string;
  market: Market;
  selectedTicker: string;
  onPreview: (ticker: string) => void;
  onOpen: (ticker: string) => void;
}) {
  const showName = market !== "us";
  const tableWrapRef = useRef<HTMLDivElement | null>(null);
  const dragStateRef = useRef({ active: false, startX: 0, scrollLeft: 0, moved: false });

  const startDrag = (event: MouseEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest("button, a, input, select, textarea")) return;
    const wrapper = tableWrapRef.current;
    if (!wrapper) return;
    dragStateRef.current = {
      active: true,
      startX: event.clientX,
      scrollLeft: wrapper.scrollLeft,
      moved: false
    };
    wrapper.classList.add("dragging");
  };

  const moveDrag = (event: MouseEvent<HTMLDivElement>) => {
    const wrapper = tableWrapRef.current;
    const dragState = dragStateRef.current;
    if (!wrapper || !dragState.active) return;
    const delta = event.clientX - dragState.startX;
    if (Math.abs(delta) > 3) dragState.moved = true;
    wrapper.scrollLeft = dragState.scrollLeft - delta;
  };

  const stopDrag = () => {
    tableWrapRef.current?.classList.remove("dragging");
    dragStateRef.current.active = false;
  };

  const suppressDragClick = (event: MouseEvent<HTMLDivElement>) => {
    if (!dragStateRef.current.moved) return;
    event.preventDefault();
    event.stopPropagation();
    dragStateRef.current.moved = false;
  };

  return (
    <div
      className="tableWrap"
      ref={tableWrapRef}
      onClickCapture={suppressDragClick}
      onMouseDown={startDrag}
      onMouseMove={moveDrag}
      onMouseUp={stopDrag}
      onMouseLeave={stopDrag}
    >
      <table>
        <thead>
          <tr>
            <th className="rankCell">排名</th>
            <th>代码</th>
            {showName ? <th>{"\u540d\u79f0"}</th> : null}
            <th>期权</th>
            <th>股票类型</th>
            <th>预计财报日</th>
            <th>收盘</th>
            <th>均线重心</th>
            <th>ATR</th>
            <th>ATR倍数</th>
            <th>较重心</th>
            <th>较3日前</th>
            <th>超额ATR</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isBenchmark = row.ticker === benchmark;
            const isSelected = row.ticker === selectedTicker;
            const trend = rankTrend(row);
            return (
              <tr
                key={row.ticker}
                className={`${isBenchmark ? "benchmarkRow" : ""} ${isSelected ? "selectedRow" : ""}`}
                onClick={() => onPreview(row.ticker)}
                onDoubleClick={() => onOpen(row.ticker)}
              >
                <td className="rankCell">
                  <span className="rankWithTrend">
                    <span>{row.rank}</span>
                    <span className={trend.className} aria-label={trend.label}>
                      {trend.symbol}
                    </span>
                    <RankHistoryPopover row={row} />
                  </span>
                </td>
                <td>
                  <button
                    className="tickerButton"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      onOpen(row.ticker);
                    }}
                    title={`打开 ${row.ticker} 详情页`}
                  >
                    <BarChart3 size={14} aria-hidden="true" />
                    {row.ticker}
                  </button>
                </td>
                {showName ? <td>{row.name || "--"}</td> : null}
                <td className={row.has_options === "Y" ? "optionYes" : row.has_options === "N" ? "optionNo" : "optionUnknown"}>
                  {row.has_options}
                </td>
                <td>{sectorLabel(row.sector)}</td>
                <td>{row.earnings_date || "--"}</td>
                <td>{numberText(row.close)}</td>
                <td>{numberText(row.ma_center)}</td>
                <td>{numberText(row.atr)}</td>
                <td className={row.atr_score >= 0 ? "positive" : "negative"}>{numberText(row.atr_score, 3)}</td>
                <td className={row.price_vs_center_pct >= 0 ? "positive" : "negative"}>
                  {percentText(row.price_vs_center_pct)}
                </td>
                <td className={(row.price_change_3d_pct ?? 0) >= 0 ? "positive" : "negative"}>
                  {percentText(row.price_change_3d_pct)}
                </td>
                <td className={row.excess_atr_vs_benchmark >= 0 ? "positive" : "negative"}>
                  {numberText(row.excess_atr_vs_benchmark, 3)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function DashboardPage() {
  const [market, setMarket] = useState<Market>("us");
  const [windowSize, setWindowSize] = useState(DEFAULT_WINDOW);
  const [asOfDate, setAsOfDate] = useState("");
  const [availableDates, setAvailableDates] = useState<string[]>([]);
  const [ranking, setRanking] = useState<RankingResponse | null>(null);
  const [selectedTicker, setSelectedTicker] = useState("QQQ");
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState(ALL_SECTORS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [alerts, setAlerts] = useState<RankingAlerts | null>(null);
  const [alertDismissed, setAlertDismissed] = useState(false);
  const [alertWindow, setAlertWindow] = useState(DEFAULT_WINDOW);
  const [alertLoading, setAlertLoading] = useState(false);
  const marketMeta = MARKET_OPTIONS.find((item) => item.value === market) ?? MARKET_OPTIONS[0];

  const loadAlerts = (requestedWindow = alertWindow, requestedDate = ranking?.as_of_date ?? asOfDate) => {
    setAlertLoading(true);
    fetchRankingAlerts(requestedWindow, requestedDate, market)
      .then((alertResult) => {
        setAlerts(alertResult);
        setAlertWindow(alertResult.window);
      })
      .catch(() => setAlerts(null))
      .finally(() => setAlertLoading(false));
  };

  const loadRanking = (requestedDate = asOfDate, requestedWindow = windowSize) => {
    setLoading(true);
    setError("");
    fetchRanking(requestedWindow, requestedDate, market === "us" && APPLY_ANNOUNCED_REBALANCE, market)
      .then((result) => {
        setRanking(result);
        setAsOfDate(result.as_of_date);
        if (!result.data.some((row) => row.ticker === selectedTicker)) setSelectedTicker(result.benchmark);
        loadAlerts(alertWindow, result.as_of_date);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  };

  const openAlerts = () => {
    setAlertDismissed(false);
    if (!alerts) loadAlerts(alertWindow, ranking?.as_of_date ?? asOfDate);
  };

  const changeAlertWindow = (value: number) => {
    setAlertWindow(value);
    loadAlerts(value, ranking?.as_of_date ?? asOfDate);
  };

  useEffect(() => {
    fetchRankingDates(520, market)
      .then((result) => setAvailableDates(result.dates))
      .catch(() => setAvailableDates([]));
    loadRanking("");
  }, [market]);

  const filteredRows = useMemo(() => {
    const rows = ranking?.data ?? [];
    const term = query.trim().toUpperCase();
    return rows.filter((row) => {
      const matchesQuery = !term || row.ticker.includes(term) || (row.name ?? "").toUpperCase().includes(term);
      const matchesType = typeFilter === ALL_SECTORS || sectorLabel(row.sector) === typeFilter;
      return matchesQuery && matchesType;
    });
  }, [ranking, query, typeFilter]);

  const typeOptions = useMemo(() => {
    const rows = ranking?.data ?? [];
    const types = Array.from(new Set(rows.map((row) => sectorLabel(row.sector)))).sort((a, b) => {
      const orderDiff = sectorSortValue(a) - sectorSortValue(b);
      return orderDiff || a.localeCompare(b, "zh-CN");
    });
    return [ALL_SECTORS, ...types];
  }, [ranking]);

  const selectedRow = ranking?.data.find((row) => row.ticker === selectedTicker);
  const openStock = (ticker: string) => navigateTo(`/stocks/${ticker}?date=${ranking?.as_of_date ?? asOfDate}&market=${market}`);

  return (
    <main className="app">
      <header className="topbar">
        <div>
          <p className="eyebrow">{marketMeta.eyebrow}</p>
          <h1>{marketMeta.title}</h1>
        </div>
        <div className="summaryStrip">
          <span className="marketSwitch" aria-label="市场切换">
            {MARKET_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={market === option.value ? "active" : ""}
                onClick={() => {
                  setMarket(option.value);
                  setAsOfDate("");
                  setRanking(null);
                  setAlerts(null);
                  setSelectedTicker(option.benchmark);
                  setTypeFilter(ALL_SECTORS);
                }}
              >
                {option.label}
              </button>
            ))}
          </span>
          <span>{ranking ? `${ranking.count} 支` : "--"}</span>
          <span>基准 {ranking?.benchmark ?? marketMeta.benchmark}</span>
          <span>基准排名 {ranking?.benchmark_rank ?? "--"}</span>
          <span>计算日期 {(ranking?.as_of_date ?? asOfDate) || "--"}</span>
          {market === "us" ? (
            <span>已应用 2026-06-22 调整名单</span>
          ) : market === "cn" ? (
            <span>前复权日线 / 中证500基准</span>
          ) : (
            <span>前复权日线 / 恒生科技基准</span>
          )}
          <button className="monitorButton" type="button" onClick={openAlerts}>
            <Activity size={16} aria-hidden="true" />
            排名监测
          </button>
        </div>
      </header>

      {alerts && !alertDismissed ? (
        <RankingAlertCard
          alerts={alerts}
          market={market}
          activeWindow={alertWindow}
          loading={alertLoading}
          onWindowChange={changeAlertWindow}
          onClose={() => setAlertDismissed(true)}
        />
      ) : null}

      <section className="toolbar">
        <div className="segmentedControl" aria-label="重心窗口">
          <span>重心窗口</span>
          {WINDOW_OPTIONS.map((value) => (
            <button
              key={value}
              type="button"
              className={windowSize === value ? "active" : ""}
              onClick={() => {
                setWindowSize(value);
                loadRanking(asOfDate, value);
              }}
            >
              {value}日
            </button>
          ))}
        </div>
        <TradingCalendar value={asOfDate} availableDates={availableDates} onChange={setAsOfDate} />
        <label className="selectBox">
          <span>股票类型</span>
          <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
            {typeOptions.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="searchBox">
          <Search size={16} aria-hidden="true" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索代码" />
        </label>
        <button className="primaryButton" type="button" onClick={() => loadRanking()} disabled={loading}>
          <RefreshCw size={16} aria-hidden="true" />
          {loading ? "计算中" : "刷新"}
        </button>
      </section>

      {error ? <div className="errorLine">{error}</div> : null}

      <section className="workspace">
        <section className="rankingPanel">
          <div className="panelHeader">
            <div>
              <p className="eyebrow">
                Window {ranking?.window ?? windowSize} / Close {(ranking?.as_of_date ?? asOfDate) || "--"}
              </p>
              <h2>排名表</h2>
            </div>
            <span className="statusText">
              {selectedRow ? `${selectedRow.ticker} ${numberText(selectedRow.atr_score, 3)} ATR` : "请选择股票"}
            </span>
          </div>
          <RankingTable
            rows={filteredRows}
            benchmark={ranking?.benchmark ?? marketMeta.benchmark}
            market={market}
            selectedTicker={selectedTicker}
            onPreview={setSelectedTicker}
            onOpen={openStock}
          />
        </section>
        <MiniChartPanel ticker={selectedTicker} asOfDate={ranking?.as_of_date ?? asOfDate} market={market} />
      </section>
    </main>
  );
}

function buildRelativeStrength(stockBars: DailyBar[], benchmarkBars: DailyBar[]) {
  const benchmarkByDate = new Map(benchmarkBars.map((bar) => [bar.date, bar.close]));
  const aligned = stockBars.filter((bar) => benchmarkByDate.has(bar.date));
  if (!aligned.length) return [];
  const firstStock = aligned[0].close;
  const firstBenchmark = benchmarkByDate.get(aligned[0].date) ?? 1;
  return aligned.map((bar) => ({
    time: toTimestamp(bar.date),
    value: ((bar.close / firstStock) / ((benchmarkByDate.get(bar.date) ?? firstBenchmark) / firstBenchmark)) * 100
  }));
}

function useStockData(ticker: string, asOfDate: string, market: Market) {
  const [stockBars, setStockBars] = useState<DailyBar[]>([]);
  const [benchmarkBars, setBenchmarkBars] = useState<DailyBar[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    const benchmark = marketBenchmark(market);
    Promise.all([fetchDailyBars(ticker, 280, asOfDate, market), fetchDailyBars(benchmark, 280, asOfDate, market)])
      .then(([stockResult, benchmarkResult]) => {
        if (!alive) return;
        setStockBars(stockResult.data);
        setBenchmarkBars(benchmarkResult.data);
      })
      .catch((err: Error) => {
        if (alive) setError(err.message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [ticker, asOfDate, market]);

  return { stockBars, benchmarkBars, loading, error };
}

function StockPriceChart({ bars }: { bars: DailyBar[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    containerRef.current.innerHTML = "";
    const chart = createChart(containerRef.current, baseChartOptions(PRICE_CHART_HEIGHT));
    const tooltip = document.createElement("div");
    tooltip.className = "chartTooltip";
    tooltip.style.display = "none";
    containerRef.current.appendChild(tooltip);
    const candleSeries = chart.addSeries(CandlestickSeries, candleStyle());
    const ma5 = chart.addSeries(LineSeries, { color: "#1f6feb", lineWidth: 2, title: "MA5" });
    const ma10 = chart.addSeries(LineSeries, { color: "#d27a00", lineWidth: 2, title: "MA10" });
    const ma20 = chart.addSeries(LineSeries, { color: "#6f42c1", lineWidth: 2, title: "MA20" });
    const ma50 = chart.addSeries(LineSeries, { color: "#0f9f6e", lineWidth: 2, title: "MA50" });
    const ma200 = chart.addSeries(LineSeries, { color: "#7b8794", lineWidth: 2, title: "MA200" });

    const resize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    resize();
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(containerRef.current);

    candleSeries.setData(bars.map((bar) => ({ time: toTimestamp(bar.date), open: bar.open, high: bar.high, low: bar.low, close: bar.close })));
    ma5.setData(movingAverageData(bars, 5));
    ma10.setData(movingAverageData(bars, 10));
    ma20.setData(movingAverageData(bars, 20));
    ma50.setData(movingAverageData(bars, 50));
    ma200.setData(movingAverageData(bars, 200));
    chart.timeScale().fitContent();
    if (bars.length > 80) chart.timeScale().setVisibleLogicalRange({ from: bars.length - 80, to: bars.length - 1 });

    const barsByTime = new Map(bars.map((bar) => [String(toTimestamp(bar.date)), bar]));
    chart.subscribeCrosshairMove((param: any) => {
      if (!containerRef.current || !param.point || param.point.x < 0 || param.point.y < 0) {
        tooltip.style.display = "none";
        return;
      }
      const bar = barsByTime.get(timeKey(param.time));
      if (!bar) {
        tooltip.style.display = "none";
        return;
      }
      tooltip.innerHTML = `
        <strong>${bar.date}</strong>
        <span>开盘 ${numberText(bar.open)}</span>
        <span>最高 ${numberText(bar.high)}</span>
        <span>最低 ${numberText(bar.low)}</span>
        <span>收盘 ${numberText(bar.close)}</span>
        <span>成交量 ${volumeText(bar.volume)}</span>
      `;
      const box = containerRef.current.getBoundingClientRect();
      const left = Math.min(param.point.x + 16, box.width - 160);
      const top = Math.min(param.point.y + 16, box.height - 148);
      tooltip.style.transform = `translate(${Math.max(8, left)}px, ${Math.max(8, top)}px)`;
      tooltip.style.display = "grid";
    });

    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, [bars]);

  return <div className="largeChartShell" ref={containerRef} />;
}

function VolumeChart({ bars }: { bars: DailyBar[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    containerRef.current.innerHTML = "";
    const chart = createChart(containerRef.current, baseChartOptions(DETAIL_SUB_CHART_HEIGHT));
    const tooltip = document.createElement("div");
    tooltip.className = "chartTooltip volumeTooltip";
    tooltip.style.display = "none";
    containerRef.current.appendChild(tooltip);
    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: "#8aa0b8",
      priceFormat: { type: "volume" },
      priceScaleId: ""
    });
    const resize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    resize();
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(containerRef.current);
    volumeSeries.setData(
      bars.map((bar, index) => ({
        time: toTimestamp(bar.date),
        value: bar.volume ?? 0,
        color: index > 0 && bar.close < bars[index - 1].close ? "#dca0a0" : "#8ac7b0"
      }))
    );
    chart.timeScale().fitContent();
    if (bars.length > 80) chart.timeScale().setVisibleLogicalRange({ from: bars.length - 80, to: bars.length - 1 });
    const barsByTime = new Map(bars.map((bar) => [String(toTimestamp(bar.date)), bar]));
    chart.subscribeCrosshairMove((param: any) => {
      if (!containerRef.current || !param.point || param.point.x < 0 || param.point.y < 0) {
        tooltip.style.display = "none";
        return;
      }
      const bar = barsByTime.get(timeKey(param.time));
      if (!bar) {
        tooltip.style.display = "none";
        return;
      }
      tooltip.innerHTML = `
        <strong>${bar.date}</strong>
        <span>成交量 ${volumeText(bar.volume)}</span>
        <span>收盘 ${numberText(bar.close)}</span>
      `;
      const box = containerRef.current.getBoundingClientRect();
      const left = Math.min(param.point.x + 16, box.width - 150);
      const top = Math.min(param.point.y + 16, box.height - 92);
      tooltip.style.transform = `translate(${Math.max(8, left)}px, ${Math.max(8, top)}px)`;
      tooltip.style.display = "grid";
    });
    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, [bars]);

  return <div className="subChartShell" ref={containerRef} />;
}

function RelativeStrengthChart({ stockBars, benchmarkBars }: { stockBars: DailyBar[]; benchmarkBars: DailyBar[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const relativeData = useMemo(() => buildRelativeStrength(stockBars, benchmarkBars), [benchmarkBars, stockBars]);

  useEffect(() => {
    if (!containerRef.current) return;
    containerRef.current.innerHTML = "";
    const chart = createChart(containerRef.current, baseChartOptions(DETAIL_SUB_CHART_HEIGHT));
    const line = chart.addSeries(LineSeries, { color: "#1f6feb", lineWidth: 2, title: "Relative to QQQ" });
    const resize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    resize();
    window.addEventListener("resize", resize);
    line.setData(relativeData);
    chart.timeScale().fitContent();
    if (relativeData.length > 80) {
      chart.timeScale().setVisibleLogicalRange({ from: relativeData.length - 80, to: relativeData.length - 1 });
    }
    return () => {
      window.removeEventListener("resize", resize);
      chart.remove();
    };
  }, [relativeData]);

  return <div className="subChartShell" ref={containerRef} />;
}

function compactMarketCap(value: string) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return "--";
  if (numeric >= 1_000_000_000_000) return `${numberText(numeric / 1_000_000_000_000, 2)}T`;
  if (numeric >= 1_000_000_000) return `${numberText(numeric / 1_000_000_000, 1)}B`;
  if (numeric >= 1_000_000) return `${numberText(numeric / 1_000_000, 1)}M`;
  return numberText(numeric, 0);
}

function cnyMarketCapText(value: string) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return "--";
  return `${numberText(numeric, 0)}亿`;
}

function cnPercentText(value: string) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "--";
  return percentText(numeric);
}

function CompanyProfileCard({ profile }: { profile: CompanyProfile | null }) {
  return (
    <section className="companyProfileCard">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Company Profile</p>
          <h2>公司简介</h2>
        </div>
        <span className="statusText">{profile?.source ? `来源 ${profile.source}` : "暂无缓存"}</span>
      </div>
      {profile?.summary_zh ? (
        <>
          <div className="profileMeta">
            <strong>{profile.name || profile.ticker}</strong>
            <span>{profile.primary_exchange || profile.exchange || "--"}</span>
            <span>{profile.sic_description || "--"}</span>
            <span>市值 {compactMarketCap(profile.market_cap)}</span>
            {profile.homepage_url ? (
              <a href={profile.homepage_url} target="_blank" rel="noreferrer">
                官网
              </a>
            ) : null}
          </div>
          <p className="profileSummary">{profile.summary_zh}</p>
          <p className="profileUpdated">更新 {profile.updated_at || "--"}</p>
        </>
      ) : (
        <p className="profileSummary mutedText">当前还没有这只股票的公司简介缓存。可以运行公司资料更新脚本后再查看。</p>
      )}
    </section>
  );
}

function StockPeersCard({ peers }: { peers: StockPeers | null }) {
  const leaders = peers?.a_share_leaders ?? [];
  const keywords = (peers?.a_share_keywords ?? "")
    .split(";")
    .map((item) => item.trim())
    .filter(Boolean);
  const sourceText =
    peers?.source === "csv_mapping"
      ? "CSV映射"
      : peers?.source === "manual_rule"
        ? "人工规则"
        : "行业兜底";

  return (
    <section className="stockPeersCard">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Sector Peers</p>
          <h2>细分赛道与 A股对标</h2>
        </div>
        <span className="statusText">{sourceText}</span>
      </div>
      <div className="peerSummary">
        <div>
          <span>细分类型</span>
          <strong>{peers?.sub_type_cn || "暂无分类"}</strong>
        </div>
        <div>
          <span>匹配关键词</span>
          <p>{keywords.length ? keywords.join(" / ") : "--"}</p>
        </div>
      </div>
      {leaders.length ? (
        <div className="peerLeaderGrid">
          {leaders.map((leader: AShareLeader) => (
            <article key={`${leader.code}-${leader.rank}`} className="peerLeaderCard">
              <div className="peerLeaderTop">
                <span>#{leader.rank}</span>
                <strong>{leader.name}</strong>
                <em>{leader.code}</em>
              </div>
              <div className="peerLeaderMetrics">
                <div>
                  <span>总市值</span>
                  <strong>{cnyMarketCapText(leader.market_cap_100m_cny)}</strong>
                </div>
                <div>
                  <span>涨跌幅</span>
                  <strong className={Number(leader.change_pct) >= 0 ? "positive" : "negative"}>
                    {cnPercentText(leader.change_pct)}
                  </strong>
                </div>
                <div>
                  <span>行业</span>
                  <strong>{leader.industry_boards || "--"}</strong>
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="profileSummary mutedText">
          当前细分类型还没有匹配到 A股龙头。可以补充细分规则或概念板块缓存后重新生成。
        </p>
      )}
      <p className="peerFootnote">A股对标仅用于产业链和情绪参照，不代表业务完全一致或投资替代关系。</p>
    </section>
  );
}

function ChartGuide({ onClose }: { onClose: () => void }) {
  return (
    <aside className="guidePanel">
      <div className="guideHeader">
        <div>
          <p className="eyebrow">Chart Guide</p>
          <h2>图表怎么看</h2>
        </div>
        <button className="iconButton" type="button" onClick={onClose} aria-label="关闭说明">
          ×
        </button>
      </div>
      <article className="guideArticle">
        <h3>K线与均线</h3>
        <p>K线用于观察价格结构。MA5/10偏短线，MA20偏中短趋势，MA50/200用于判断更大的趋势背景。</p>
        <p>价格在主要均线上方，且短期均线高于长期均线时，趋势通常更健康；反复跌回MA20或MA50下方时，需要降低强势预期。</p>
        <h3>成交量</h3>
        <p>成交量用于确认价格动作。上涨放量通常说明买盘更积极；下跌放量说明抛压更明显。</p>
        <p>成交量/20日均量大于1，表示当天活跃度高于近20日平均水平；低于1则说明参与度偏低。</p>
        <h3>相对QQQ强度</h3>
        <p>5D/10D/20D/60D相对收益 = 股票同期涨幅 - QQQ同期涨幅。正数代表这段时间跑赢QQQ，负数代表跑输。</p>
        <p>5D更敏感，适合看短线资金是否刚开始变强；10D接近当前榜单的观察节奏；20D适合看一个月左右的趋势延续；60D用于确认中期相对强弱。</p>
        <p>超额ATR强度沿用首页排名口径：股票ATR分数 - QQQ ATR分数。它不是普通收益率，而是看股票相对自身波动幅度，是否比QQQ更强。</p>
        <p>如果短中期相对收益为正，同时超额ATR强度也为正，说明它既跑赢QQQ，也在当前波动环境下更有强势弹性。</p>
      </article>
    </aside>
  );
}

function StockDetailPage({ ticker, initialDate, market }: { ticker: string; initialDate: string; market: Market }) {
  const [asOfDate, setAsOfDate] = useState(initialDate);
  const [availableDates, setAvailableDates] = useState<string[]>([]);
  const [ranking, setRanking] = useState<RankingResponse | null>(null);
  const [rankWindow, setRankWindow] = useState(DEFAULT_WINDOW);
  const [rankLoading, setRankLoading] = useState(false);
  const [companyProfile, setCompanyProfile] = useState<CompanyProfile | null>(null);
  const [stockPeers, setStockPeers] = useState<StockPeers | null>(null);
  const [showGuide, setShowGuide] = useState(false);
  const { stockBars, benchmarkBars, loading, error } = useStockData(ticker, asOfDate, market);
  const benchmarkLabel = market === "cn" ? "中证500" : market === "hk" ? "恒生科技" : "QQQ";

  useEffect(() => {
    fetchRankingDates(520, market)
      .then((result) => {
        setAvailableDates(result.dates);
        if (!asOfDate && result.dates.length) setAsOfDate(result.dates[result.dates.length - 1]);
      })
      .catch(() => setAvailableDates([]));
  }, []);

  useEffect(() => {
    if (!asOfDate) return;
    let alive = true;
    setRankLoading(true);
    fetchRanking(rankWindow, asOfDate, market === "us" && APPLY_ANNOUNCED_REBALANCE, market)
      .then((result) => {
        if (alive) setRanking(result);
      })
      .catch(() => {
        if (alive) setRanking(null);
      })
      .finally(() => {
        if (alive) setRankLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [asOfDate, rankWindow]);

  useEffect(() => {
    let alive = true;
    fetchStockProfile(ticker)
      .then((result) => {
        if (alive) setCompanyProfile(result);
      })
      .catch(() => {
        if (alive) setCompanyProfile(null);
      });
    return () => {
      alive = false;
    };
  }, [ticker]);

  useEffect(() => {
    let alive = true;
    fetchStockPeers(ticker)
      .then((result) => {
        if (alive) setStockPeers(result);
      })
      .catch(() => {
        if (alive) setStockPeers(null);
      });
    return () => {
      alive = false;
    };
  }, [ticker]);

  const latest = stockBars.length ? stockBars[stockBars.length - 1] : undefined;
  const previous = stockBars.length > 1 ? stockBars[stockBars.length - 2] : undefined;
  const changePct = latest && previous ? (latest.close / previous.close - 1) * 100 : null;
  const recent20 = stockBars.slice(-20);
  const high20 = recent20.length ? Math.max(...recent20.map((bar) => bar.high)) : null;
  const low20 = recent20.length ? Math.min(...recent20.map((bar) => bar.low)) : null;
  const atr20 = latestAtr(stockBars, 20);
  const avgVolume20 =
    recent20.length && recent20.some((bar) => bar.volume !== null)
      ? recent20.reduce((sum, bar) => sum + (bar.volume ?? 0), 0) / recent20.length
      : null;
  const volumeRatio = latest?.volume && avgVolume20 ? latest.volume / avgVolume20 : null;
  const relativeWindows = [5, 10, 20, 60].map((window) => ({
    window,
    value: relativeReturn(stockBars, benchmarkBars, window)
  }));
  const relative20 = relativeWindows.find((item) => item.window === 20)?.value ?? null;
  const rankingRow = ranking?.data.find((row) => row.ticker === ticker);
  const excessAtrStrength = rankingRow?.excess_atr_vs_benchmark ?? null;

  const updateDate = (date: string) => {
    setAsOfDate(date);
    window.history.replaceState({}, "", `/stocks/${ticker}?date=${date}&market=${market}`);
  };

  return (
    <main className="app detailPage">
      <header className="topbar">
        <div>
          <button className="ghostButton" type="button" onClick={() => navigateTo("/")}>
            <ArrowLeft size={16} aria-hidden="true" />
            返回榜单
          </button>
          <p className="eyebrow">Stock Workspace</p>
          <h1>{ticker} 技术面详情</h1>
        </div>
        <div className="summaryStrip">
          <span>收盘日期 {(latest?.date ?? asOfDate) || "--"}</span>
          <span>收盘 {numberText(latest?.close)}</span>
          <span className={changePct !== null && changePct >= 0 ? "positivePill" : "negativePill"}>
            日涨跌 {percentText(changePct)}
          </span>
          <button className="guideButton" type="button" onClick={() => setShowGuide((current) => !current)}>
            <HelpCircle size={16} aria-hidden="true" />
            图表说明
          </button>
        </div>
      </header>
      {showGuide ? <ChartGuide onClose={() => setShowGuide(false)} /> : null}

      <section className="toolbar">
        <TradingCalendar value={asOfDate} availableDates={availableDates} onChange={updateDate} />
        <button className="primaryButton" type="button" onClick={() => setAsOfDate(asOfDate)} disabled={loading}>
          <RefreshCw size={16} aria-hidden="true" />
          {loading ? "加载中" : "刷新"}
        </button>
      </section>

      {error ? <div className="errorLine">{error}</div> : null}

      <CompanyProfileCard profile={companyProfile} />
      <StockPeersCard peers={stockPeers} />

      <section className="detailInsightGrid">
        <RankingTrendCard
          row={rankingRow}
          windowSize={rankWindow}
          loading={rankLoading}
          onWindowChange={setRankWindow}
        />
        <section className="metricGrid compactMetricGrid">
          <div className="metricItem">
            <span>20日高点</span>
            <strong>{numberText(high20)}</strong>
          </div>
          <div className="metricItem">
            <span>20日低点</span>
            <strong>{numberText(low20)}</strong>
          </div>
          <div className="metricItem">
            <span>ATR20</span>
            <strong>{numberText(atr20)}</strong>
          </div>
          <div className="metricItem">
            <span>成交量/20日均量</span>
            <strong>{numberText(volumeRatio, 2)}x</strong>
          </div>
          <div className="metricItem">
            <span>20D相对{benchmarkLabel}</span>
            <strong className={relative20 !== null && relative20 >= 0 ? "positive" : "negative"}>
              {percentText(relative20)}
            </strong>
          </div>
          <div className="metricItem">
            <span>超额ATR强度</span>
            <strong className={excessAtrStrength !== null && excessAtrStrength >= 0 ? "positive" : "negative"}>
              {numberText(excessAtrStrength, 3)}
            </strong>
          </div>
        </section>
      </section>

      <section className="analysisGrid">
        <section className="analysisMain">
          <div className="panelHeader">
            <div>
              <p className="eyebrow">Price / Moving Averages</p>
              <h2>K线与均线</h2>
            </div>
          </div>
          <div className="legendLine">
            <span className="legendDot candle" /> K线
            <span className="legendDot ma5" /> MA5
            <span className="legendDot ma10" /> MA10
            <span className="legendDot ma20" /> MA20
            <span className="legendDot ma50" /> MA50
            <span className="legendDot ma200" /> MA200
          </div>
          <StockPriceChart bars={stockBars} />
        </section>

        <aside className="analysisSide compactSide">
          <section className="relativeStrengthCard">
            <p className="eyebrow">Relative {benchmarkLabel}</p>
            <h2>相对 {benchmarkLabel} 强度</h2>
            <p className="cardIntro">
              这里比较的是股票和 QQQ 在同一段时间里的表现差。正数表示跑赢 QQQ，负数表示跑输 QQQ。
            </p>
            <div className="relativeList">
              {relativeWindows.map((item) => (
                <div key={item.window} className="maRow">
                  <span>{item.window}D</span>
                  <strong className={item.value !== null && item.value >= 0 ? "positive" : "negative"}>
                    {percentText(item.value)}
                  </strong>
                  <em>vs {benchmarkLabel}</em>
                </div>
              ))}
              <div className="maRow">
                <span>ATR</span>
                <strong className={excessAtrStrength !== null && excessAtrStrength >= 0 ? "positive" : "negative"}>
                  {numberText(excessAtrStrength, 3)}
                </strong>
                <em>超额</em>
              </div>
            </div>
            <div className="relativeNotes">
              <p><strong>5D</strong> 看短线是否刚开始转强。</p>
              <p><strong>10D</strong> 对应当前榜单的主要观察节奏。</p>
              <p><strong>20D</strong> 看一个月左右的趋势延续。</p>
              <p><strong>60D</strong> 用来确认中期相对强弱。</p>
              <p><strong>ATR</strong> 是首页同口径的超额强度，越高说明相对 QQQ 的波动强势越明显。</p>
            </div>
          </section>
        </aside>
      </section>

      <section className="lowerCharts singleChart">
        <section>
          <div className="panelHeader">
            <div>
              <p className="eyebrow">Volume</p>
              <h2>成交量</h2>
            </div>
          </div>
          <VolumeChart bars={stockBars} />
        </section>
      </section>
    </main>
  );
}

export default function App() {
  const [route, setRoute] = useState<RouteState>(() => parseRoute());

  useEffect(() => {
    const handleRoute = () => setRoute(parseRoute());
    window.addEventListener("popstate", handleRoute);
    return () => window.removeEventListener("popstate", handleRoute);
  }, []);

  if (route.page === "stock" && route.ticker) {
    return <StockDetailPage ticker={route.ticker} initialDate={route.date ?? ""} market={route.market ?? "us"} />;
  }
  return <DashboardPage />;
}
