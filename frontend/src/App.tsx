import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  BarChart3,
  CalendarDays,
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
  fetchRankingDates,
  type DailyBar,
  type RankingResponse,
  type RankingRow
} from "./api";

const DEFAULT_WINDOW = 10;
const APPLY_ANNOUNCED_REBALANCE = true;
const CHART_VISIBLE_DAYS = 20;
const PRICE_CHART_HEIGHT = 460;
const DETAIL_SUB_CHART_HEIGHT = 260;

type RouteState = {
  page: "dashboard" | "stock";
  ticker?: string;
  date?: string;
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
  return {
    page: "stock",
    ticker: match[1].toUpperCase(),
    date: new URLSearchParams(window.location.search).get("date") ?? ""
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

function MiniChartPanel({ ticker, asOfDate }: { ticker: string; asOfDate: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [bars, setBars] = useState<DailyBar[]>([]);

  useEffect(() => {
    let alive = true;
    fetchDailyBars(ticker, 120, asOfDate).then((result) => {
      if (alive) setBars(result.data);
    });
    return () => {
      alive = false;
    };
  }, [ticker, asOfDate]);

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
  selectedTicker,
  onPreview,
  onOpen
}: {
  rows: RankingRow[];
  benchmark: string;
  selectedTicker: string;
  onPreview: (ticker: string) => void;
  onOpen: (ticker: string) => void;
}) {
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            <th className="rankCell">排名</th>
            <th>代码</th>
            <th>收盘日期</th>
            <th>收盘</th>
            <th>最新均线</th>
            <th>均线重心</th>
            <th>ATR</th>
            <th>ATR倍数</th>
            <th>较重心</th>
            <th>超额ATR</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isBenchmark = row.ticker === benchmark;
            const isSelected = row.ticker === selectedTicker;
            return (
              <tr
                key={row.ticker}
                className={`${isBenchmark ? "benchmarkRow" : ""} ${isSelected ? "selectedRow" : ""}`}
                onClick={() => onPreview(row.ticker)}
                onDoubleClick={() => onOpen(row.ticker)}
              >
                <td className="rankCell">{row.rank}</td>
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
                <td>{row.date}</td>
                <td>{numberText(row.close)}</td>
                <td>{numberText(row.latest_ma)}</td>
                <td>{numberText(row.ma_center)}</td>
                <td>{numberText(row.atr)}</td>
                <td className={row.atr_score >= 0 ? "positive" : "negative"}>{numberText(row.atr_score, 3)}</td>
                <td className={row.price_vs_center_pct >= 0 ? "positive" : "negative"}>
                  {percentText(row.price_vs_center_pct)}
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
  const [windowSize, setWindowSize] = useState(DEFAULT_WINDOW);
  const [asOfDate, setAsOfDate] = useState("");
  const [availableDates, setAvailableDates] = useState<string[]>([]);
  const [ranking, setRanking] = useState<RankingResponse | null>(null);
  const [selectedTicker, setSelectedTicker] = useState("QQQ");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadRanking = (requestedDate = asOfDate) => {
    setLoading(true);
    setError("");
    fetchRanking(windowSize, requestedDate, APPLY_ANNOUNCED_REBALANCE)
      .then((result) => {
        setRanking(result);
        setAsOfDate(result.as_of_date);
        if (!result.data.some((row) => row.ticker === selectedTicker)) setSelectedTicker(result.benchmark);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchRankingDates(520)
      .then((result) => setAvailableDates(result.dates))
      .catch(() => setAvailableDates([]));
    loadRanking("");
  }, []);

  const filteredRows = useMemo(() => {
    const rows = ranking?.data ?? [];
    const term = query.trim().toUpperCase();
    if (!term) return rows;
    return rows.filter((row) => row.ticker.includes(term));
  }, [ranking, query]);

  const selectedRow = ranking?.data.find((row) => row.ticker === selectedTicker);
  const openStock = (ticker: string) => navigateTo(`/stocks/${ticker}?date=${ranking?.as_of_date ?? asOfDate}`);

  return (
    <main className="app">
      <header className="topbar">
        <div>
          <p className="eyebrow">Nasdaq-100 Relative Strength</p>
          <h1>纳指成分股 ATR 排名</h1>
        </div>
        <div className="summaryStrip">
          <span>{ranking ? `${ranking.count} 支` : "--"}</span>
          <span>基准 {ranking?.benchmark ?? "QQQ"}</span>
          <span>基准排名 {ranking?.benchmark_rank ?? "--"}</span>
          <span>计算日期 {(ranking?.as_of_date ?? asOfDate) || "--"}</span>
          <span>已应用 2026-06-22 调整名单</span>
        </div>
      </header>

      <section className="toolbar">
        <label className="field">
          <span>重心窗口</span>
          <input
            type="number"
            min={2}
            max={60}
            value={windowSize}
            onChange={(event) => setWindowSize(Number(event.target.value))}
          />
        </label>
        <TradingCalendar value={asOfDate} availableDates={availableDates} onChange={setAsOfDate} />
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
            benchmark={ranking?.benchmark ?? "QQQ"}
            selectedTicker={selectedTicker}
            onPreview={setSelectedTicker}
            onOpen={openStock}
          />
        </section>
        <MiniChartPanel ticker={selectedTicker} asOfDate={ranking?.as_of_date ?? asOfDate} />
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

function useStockData(ticker: string, asOfDate: string) {
  const [stockBars, setStockBars] = useState<DailyBar[]>([]);
  const [benchmarkBars, setBenchmarkBars] = useState<DailyBar[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    Promise.all([fetchDailyBars(ticker, 280, asOfDate), fetchDailyBars("QQQ", 280, asOfDate)])
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
  }, [ticker, asOfDate]);

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

function StockDetailPage({ ticker, initialDate }: { ticker: string; initialDate: string }) {
  const [asOfDate, setAsOfDate] = useState(initialDate);
  const [availableDates, setAvailableDates] = useState<string[]>([]);
  const [ranking, setRanking] = useState<RankingResponse | null>(null);
  const [showGuide, setShowGuide] = useState(false);
  const { stockBars, benchmarkBars, loading, error } = useStockData(ticker, asOfDate);

  useEffect(() => {
    fetchRankingDates(520)
      .then((result) => {
        setAvailableDates(result.dates);
        if (!asOfDate && result.dates.length) setAsOfDate(result.dates[result.dates.length - 1]);
      })
      .catch(() => setAvailableDates([]));
  }, []);

  useEffect(() => {
    if (!asOfDate) return;
    let alive = true;
    fetchRanking(DEFAULT_WINDOW, asOfDate, APPLY_ANNOUNCED_REBALANCE)
      .then((result) => {
        if (alive) setRanking(result);
      })
      .catch(() => {
        if (alive) setRanking(null);
      });
    return () => {
      alive = false;
    };
  }, [asOfDate]);

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
    window.history.replaceState({}, "", `/stocks/${ticker}?date=${date}`);
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

      <section className="metricGrid">
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
          <span>20D相对QQQ</span>
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
            <p className="eyebrow">Relative QQQ</p>
            <h2>相对 QQQ 强度</h2>
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
                  <em>vs QQQ</em>
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
    return <StockDetailPage ticker={route.ticker} initialDate={route.date ?? ""} />;
  }
  return <DashboardPage />;
}
