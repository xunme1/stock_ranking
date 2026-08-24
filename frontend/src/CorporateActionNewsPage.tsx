import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Building2,
  CalendarDays,
  ChevronDown,
  ExternalLink,
  Newspaper,
  RefreshCw,
  ShieldCheck,
  TrendingDown
} from "lucide-react";
import {
  fetchBuybackChart,
  fetchCorporateActionNews,
  type BuybackChartResponse,
  type CorporateActionEventType,
  type CorporateActionNewsItem,
  type CorporateActionNewsResponse,
  type Market
} from "./api";
import { createChart, HistogramSeries, LineSeries, type UTCTimestamp } from "lightweight-charts";

const MARKET_OPTIONS: Array<{ value: Market; label: string; title: string }> = [
  { value: "us", label: "美股", title: "美股回购与减持新闻" },
  { value: "cn", label: "A股", title: "A股回购与减持新闻" },
  { value: "hk", label: "港股", title: "港股回购与减持新闻" }
];

const EVENT_LABELS: Record<CorporateActionEventType, string> = {
  buyback: "股份回购",
  reduction: "股东减持"
};

const STAGE_LABELS: Record<CorporateActionNewsItem["event_stage"], string> = {
  announced: "已公告",
  authorized: "已授权",
  in_progress: "进行中",
  executed: "已实施",
  completed: "已完成"
};

const SOURCE_LABELS: Record<CorporateActionNewsItem["source_quality"], string> = {
  primary: "官方渠道",
  mainstream: "主流媒体",
  other: "其他来源"
};

type NewsStory = {
  key: string;
  lead: CorporateActionNewsItem;
  events: CorporateActionNewsItem[];
  inStockPool: boolean;
};

type CorporateActionNewsPageProps = {
  market: Market;
  onBack: () => void;
  onMarketChange: (market: Market) => void;
  onOpenStock: (ticker: string, market: Market) => void;
};

function isPoolEvent(item: CorporateActionNewsItem) {
  return item.in_stock_pool === true || item.in_stock_pool === 1 || item.attention_level === "high";
}

function safeExternalUrl(value: string) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : "";
  } catch {
    return "";
  }
}

function groupStories(rows: CorporateActionNewsItem[]) {
  const grouped = new Map<string, CorporateActionNewsItem[]>();
  rows.forEach((row) => {
    // A single company can be mentioned by several follow-up stories.  Keep the
    // latest item on the card and retain the previous collection results below
    // it instead of making the market feed repetitive.
    const companyKey = (row.company_identity || row.ticker || row.company_name).replace(/\s+/g, "").toLocaleUpperCase();
    const key = `${row.market}|${row.event_type}|${companyKey}`;
    grouped.set(key, [...(grouped.get(key) ?? []), row]);
  });
  return Array.from(grouped.entries()).map(([key, events]): NewsStory => {
    const sortedEvents = [...events].sort((left, right) => {
      const publishedDifference = Date.parse(right.published_at) - Date.parse(left.published_at);
      if (Number.isFinite(publishedDifference) && publishedDifference !== 0) return publishedDifference;
      const updatedDifference = Date.parse(right.updated_at) - Date.parse(left.updated_at);
      if (Number.isFinite(updatedDifference) && updatedDifference !== 0) return updatedDifference;
      return right.confidence - left.confidence;
    });
    return { key, lead: sortedEvents[0], events: sortedEvents, inStockPool: sortedEvents.some(isPoolEvent) };
  });
}

function formatDate(value: string, includeTime = false) {
  if (!value) return "--";
  const dateOnly = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (dateOnly) return `${dateOnly[1]}年${Number(dateOnly[2])}月${Number(dateOnly[3])}日`;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
    ...(includeTime ? { hour: "2-digit", minute: "2-digit" } : {})
  }).format(parsed);
}

function chartTimestamp(value: string) {
  return Math.floor(new Date(`${value}T00:00:00Z`).getTime() / 1000) as UTCTimestamp;
}

function formatShares(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "--";
  const format = (number: number) => new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(number);
  if (Math.abs(value) >= 100_000_000) return `${format(value / 100_000_000)}亿股`;
  if (Math.abs(value) >= 10_000) return `${format(value / 10_000)}万股`;
  return `${format(value)}股`;
}

function canShowBuybackChart(event: CorporateActionNewsItem) {
  return event.buyback_chart_available === true;
}

function hasDailyRepurchaseData(event: CorporateActionNewsItem) {
  return (
    event.event_type === "buyback" &&
    event.repurchase_shares_scope === "daily" &&
    typeof event.repurchase_shares === "number" &&
    event.repurchase_shares > 0
  );
}

const CHART_STATUS_TEXT: Record<CorporateActionNewsItem["buyback_chart_status"], string> = {
  available: "",
  not_eligible: "该回购未提供可核验的单日股数、日期或代码。",
  out_of_window: "回购日不在入库时保存的 10 日行情窗口内。",
  unavailable: "该回购的行情快照暂不可用。"
};

function affectedStocks(events: CorporateActionNewsItem[], market: Market) {
  const stocks = new Map<string, { key: string; label: string; ticker: string; inPool: boolean }>();
  events.forEach((event) => {
    const ticker = event.ticker ?? "";
    const label = market === "us" ? ticker || event.company_name : event.company_name || ticker;
    if (!label) return;
    const key = ticker || event.company_name;
    const existing = stocks.get(key);
    stocks.set(key, {
      key,
      label,
      ticker,
      inPool: Boolean(existing?.inPool || isPoolEvent(event))
    });
  });
  return Array.from(stocks.values());
}

function eventFacts(event: CorporateActionNewsItem) {
  return Array.from(
    new Set(
      [event.amount_text, event.quantity_text, event.ownership_change_text].filter((value) => value.trim())
    )
  ).slice(0, 4);
}

function BuybackPriceChart({ chart }: { chart: BuybackChartResponse }) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !chart.data.length || !chart.event_date || chart.repurchase_shares === null) return;
    container.innerHTML = "";
    const graph = createChart(container, {
      width: container.clientWidth,
      height: 270,
      layout: { background: { color: "#ffffff" }, textColor: "#4d6278" },
      grid: { vertLines: { color: "#edf1f6" }, horzLines: { color: "#edf1f6" } },
      leftPriceScale: { visible: true, borderColor: "#cbd6e2" },
      rightPriceScale: { visible: true, borderColor: "#cbd6e2" },
      timeScale: { borderColor: "#cbd6e2", timeVisible: false }
    });
    const tooltip = document.createElement("div");
    tooltip.className = "buybackChartTooltip";
    tooltip.style.display = "none";
    container.appendChild(tooltip);
    const closeSeries = graph.addSeries(LineSeries, {
      priceScaleId: "left",
      color: "#1976a8",
      lineWidth: 2,
      pointMarkersVisible: true,
      title: "收盘价"
    });
    const repurchaseSeries = graph.addSeries(HistogramSeries, {
      priceScaleId: "right",
      color: "#db4965",
      title: "当日回购股数"
    });
    const priceData = chart.data.map((point) => ({ time: chartTimestamp(point.price_date), value: point.close }));
    closeSeries.setData(priceData);
    repurchaseSeries.setData(
      chart.data
        .filter((point) => point.price_date === chart.event_date)
        .map((point) => ({ time: chartTimestamp(point.price_date), value: chart.repurchase_shares as number, color: "#db4965" }))
    );
    graph.timeScale().fitContent();
    const closeByTime = new Map(chart.data.map((point) => [String(chartTimestamp(point.price_date)), point]));
    graph.subscribeCrosshairMove((param: any) => {
      if (!param.point || param.point.x < 0 || param.point.y < 0 || param.time === undefined) {
        tooltip.style.display = "none";
        return;
      }
      const point = closeByTime.get(String(param.time));
      if (!point) {
        tooltip.style.display = "none";
        return;
      }
      const buybackLine = point.price_date === chart.event_date ? `<span>当日回购 ${formatShares(chart.repurchase_shares)}</span>` : "";
      tooltip.innerHTML = `<strong>${point.price_date}</strong><span>收盘价 ${point.close.toFixed(2)}</span>${buybackLine}`;
      const box = container.getBoundingClientRect();
      const left = Math.min(param.point.x + 14, box.width - 160);
      const top = Math.min(param.point.y + 14, box.height - 90);
      tooltip.style.transform = `translate(${Math.max(8, left)}px, ${Math.max(8, top)}px)`;
      tooltip.style.display = "grid";
    });
    const resize = () => graph.applyOptions({ width: container.clientWidth });
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    return () => {
      observer.disconnect();
      graph.remove();
    };
  }, [chart]);

  return <div className="buybackChartCanvas" ref={containerRef} />;
}

function BuybackChartPanel({ event }: { event: CorporateActionNewsItem }) {
  const [chart, setChart] = useState<BuybackChartResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    setChart(null);
    setError("");
    fetchBuybackChart(event.event_id)
      .then((response) => {
        if (alive) setChart(response);
      })
      .catch((err: Error) => {
        if (alive) setError(err.message || "回购走势加载失败");
      });
    return () => {
      alive = false;
    };
  }, [event.event_id]);

  if (error) return <div className="buybackChartNotice">回购走势加载失败：{error}</div>;
  if (!chart) return <div className="buybackChartNotice">正在加载回购走势...</div>;
  if (chart.status !== "available") return <div className="buybackChartNotice">{chart.message || "该回购走势暂不可用。"}</div>;

  return (
    <section className="buybackChartPanel">
      <div className="buybackChartHeader">
        <div>
          <span>Buyback Price Snapshot</span>
          <strong>
            {chart.company_name}{chart.ticker ? `（${chart.ticker}）` : ""} · 收盘价与回购股数
          </strong>
        </div>
        <small>{chart.window_start} 至 {chart.window_end}</small>
      </div>
      <div className="buybackChartLegend">
        <span className="closeLegend">收盘价</span>
        <span className="repurchaseLegend">{chart.event_date} 回购 {formatShares(chart.repurchase_shares)}</span>
      </div>
      <BuybackPriceChart chart={chart} />
    </section>
  );
}

function NewsCard({
  story,
  market,
  emphasized,
  onOpenStock
}: {
  story: NewsStory;
  market: Market;
  emphasized: boolean;
  onOpenStock: CorporateActionNewsPageProps["onOpenStock"];
}) {
  const { lead } = story;
  const [expandedChartEventId, setExpandedChartEventId] = useState<string | null>(null);
  const [historyExpanded, setHistoryExpanded] = useState(false);
  const title = lead.headline_zh || lead.headline;
  const showOriginalTitle = Boolean(lead.headline_zh && lead.headline_zh !== lead.headline);
  const stocks = affectedStocks([lead], market);
  const facts = eventFacts(lead);
  const sourceUrl = safeExternalUrl(lead.source_url);
  // A newer authorization story must not hide an earlier, eligible execution
  // chart in the same company's folded history.
  const chartEvents = story.events.filter(canShowBuybackChart);
  const unavailableChartEvents = [lead].filter((event) => hasDailyRepurchaseData(event) && !canShowBuybackChart(event));
  const expandedChartEvent = chartEvents.find((event) => event.event_id === expandedChartEventId) ?? null;
  const historicalEvents = story.events.slice(1);

  return (
    <article className={`corporateNewsCard ${emphasized ? "emphasized" : ""}`}>
      <div className="corporateNewsCardTop">
        <div className="corporateNewsBadges">
          <span className={`eventBadge ${lead.event_type}`}>{EVENT_LABELS[lead.event_type]}</span>
          <span className="stageBadge">{STAGE_LABELS[lead.event_stage]}</span>
          {emphasized ? (
            <span className="poolBadge">
              <ShieldCheck size={13} aria-hidden="true" />
              股票池
            </span>
          ) : null}
        </div>
        <span className="sourceQuality">{SOURCE_LABELS[lead.source_quality]}</span>
      </div>

      <h3>{title}</h3>
      {showOriginalTitle ? <p className="originalHeadline">{lead.headline}</p> : null}
      <p className="corporateNewsSummary">{lead.summary_zh || "该新闻暂未生成摘要，请查看原文。"}</p>

      {facts.length ? (
        <div className="corporateNewsFacts">
          {facts.map((fact) => (
            <span key={fact}>{fact}</span>
          ))}
        </div>
      ) : null}

      {chartEvents.length ? (
        <div className="buybackChartActions">
          {chartEvents.map((event) => (
            <button
              key={event.event_id}
              className={expandedChartEventId === event.event_id ? "active" : ""}
              type="button"
              onClick={() => setExpandedChartEventId((current) => (current === event.event_id ? null : event.event_id))}
            >
              <TrendingDown size={15} aria-hidden="true" />
              {expandedChartEventId === event.event_id ? "收起回购走势" : `查看${event.ticker || event.company_name}回购走势`}
            </button>
          ))}
        </div>
      ) : null}
      {unavailableChartEvents.length ? (
        <p className="buybackChartUnavailable">
          {CHART_STATUS_TEXT[unavailableChartEvents[0].buyback_chart_status]}
        </p>
      ) : null}
      {expandedChartEvent ? <BuybackChartPanel event={expandedChartEvent} /> : null}

      {historicalEvents.length ? (
        <section className="corporateNewsHistory">
          <button
            className={historyExpanded ? "expanded" : ""}
            type="button"
            onClick={() => setHistoryExpanded((current) => !current)}
            aria-expanded={historyExpanded}
          >
            <ChevronDown size={15} aria-hidden="true" />
            {historyExpanded ? "收起历史搜集记录" : `查看历史搜集记录（${historicalEvents.length}）`}
          </button>
          {historyExpanded ? (
            <ol>
              {historicalEvents.map((event) => {
                const historyUrl = safeExternalUrl(event.source_url);
                const historyTitle = event.headline_zh || event.headline;
                return (
                  <li key={event.event_id}>
                    <div className="corporateNewsHistoryMeta">
                      <span>{formatDate(event.published_at)}</span>
                      <span className="stageBadge">{STAGE_LABELS[event.event_stage]}</span>
                      <span>{event.source_domain || "来源待确认"}</span>
                    </div>
                    <p>{historyTitle}</p>
                    {historyUrl ? (
                      <a href={historyUrl} target="_blank" rel="noreferrer">
                        查看原文 <ExternalLink size={12} aria-hidden="true" />
                      </a>
                    ) : null}
                  </li>
                );
              })}
            </ol>
          ) : null}
        </section>
      ) : null}

      <div className="affectedStocks">
        <span className="affectedStocksLabel">
          <Building2 size={14} aria-hidden="true" />
          影响股票
        </span>
        <div>
          {stocks.length ? (
            stocks.map((stock) =>
              stock.ticker ? (
                <button
                  className={stock.inPool ? "poolStock" : ""}
                  type="button"
                  key={stock.key}
                  onClick={() => onOpenStock(stock.ticker, market)}
                  title={`查看 ${stock.label}`}
                >
                  {stock.label}
                </button>
              ) : (
                <span className={stock.inPool ? "poolStock" : ""} key={stock.key}>
                  {stock.label}
                </span>
              )
            )
          ) : (
            <span className="unknownStock">公司代码待确认</span>
          )}
        </div>
      </div>

      <footer className="corporateNewsMeta">
        <span>
          <CalendarDays size={14} aria-hidden="true" />
          {formatDate(lead.published_at)}
        </span>
        <span>
          <Newspaper size={14} aria-hidden="true" />
          {lead.source_domain || "来源待确认"}
        </span>
        {sourceUrl ? (
          <a href={sourceUrl} target="_blank" rel="noreferrer">
            查看原文
            <ExternalLink size={13} aria-hidden="true" />
          </a>
        ) : (
          <span>来源链接不可用</span>
        )}
      </footer>
    </article>
  );
}

function EmptySection({ children }: { children: string }) {
  return <div className="corporateNewsEmpty">{children}</div>;
}

export default function CorporateActionNewsPage({
  market,
  onBack,
  onMarketChange,
  onOpenStock
}: CorporateActionNewsPageProps) {
  const [eventType, setEventType] = useState<"all" | CorporateActionEventType>("all");
  const [response, setResponse] = useState<CorporateActionNewsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const marketMeta = MARKET_OPTIONS.find((option) => option.value === market) ?? MARKET_OPTIONS[0];

  const loadNews = () => {
    setLoading(true);
    setError("");
    fetchCorporateActionNews(market, eventType)
      .then(setResponse)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    setResponse(null);
    loadNews();
  }, [market, eventType]);

  const stories = useMemo(() => groupStories(response?.data ?? []), [response]);
  const highlightedStories = stories.filter((story) => story.inStockPool);
  const regularStories = stories.filter((story) => !story.inStockPool);
  const unavailable = response?.status === "unavailable";

  return (
    <main className="app corporateActionPage">
      <header className="topbar corporateActionTopbar">
        <div>
          <button className="ghostButton" type="button" onClick={onBack}>
            <ArrowLeft size={16} aria-hidden="true" />
            返回主页
          </button>
          <p className="eyebrow">Corporate Action Monitor</p>
          <h1>{marketMeta.title}</h1>
          <p className="corporateActionLead">聚合最近 30 天的股份回购和现有股东减持动态，股票池命中事件优先展示。</p>
        </div>
        <div className="summaryStrip corporateActionHeaderActions">
          <span className="marketSwitch" aria-label="新闻市场切换">
            {MARKET_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={market === option.value ? "active" : ""}
                onClick={() => onMarketChange(option.value)}
              >
                {option.label}
              </button>
            ))}
          </span>
          <button className="monitorButton" type="button" onClick={loadNews} disabled={loading}>
            <RefreshCw size={16} aria-hidden="true" />
            {loading ? "加载中" : "刷新页面"}
          </button>
        </div>
      </header>

      <section className="corporateActionOverview">
        <div className="corporateActionStats">
          <div>
            <span>监测窗口</span>
            <strong>{response?.window_start && response?.as_of_date ? `${response.window_start} 至 ${response.as_of_date}` : "最近 30 天"}</strong>
          </div>
          <div>
            <span>公司动态</span>
            <strong>{response ? stories.length : "--"}</strong>
          </div>
          <div className="highStat">
            <span>股票池命中</span>
            <strong>{response ? highlightedStories.length : "--"}</strong>
          </div>
          <div>
            <span>股票池外</span>
            <strong>{response ? regularStories.length : "--"}</strong>
          </div>
        </div>
        <div className="corporateActionControlRow">
          <div className="corporateEventFilter" aria-label="事件类型筛选">
            {[
              ["all", "全部事件"],
              ["buyback", "股份回购"],
              ["reduction", "股东减持"]
            ].map(([value, label]) => (
              <button
                type="button"
                className={eventType === value ? "active" : ""}
                key={value}
                onClick={() => setEventType(value as "all" | CorporateActionEventType)}
              >
                {label}
              </button>
            ))}
          </div>
          <span className={`freshnessState ${response?.stale ? "stale" : ""}`}>
            数据截至 {formatDate(response?.refresh_through_date ?? "")}
          </span>
        </div>
      </section>

      {response?.stale && response.status !== "unavailable" ? (
        <div className="corporateNewsNotice">当前展示的是最近一次成功采集的数据，采集截止日期早于查询日期。</div>
      ) : null}
      {error ? <div className="errorLine">{error}</div> : null}
      {loading ? <EmptySection>正在加载回购与减持新闻...</EmptySection> : null}
      {!loading && unavailable ? <EmptySection>新闻采集服务尚无成功数据，请先运行受控采集脚本。</EmptySection> : null}

      {!loading && !unavailable && !error ? (
        <>
          <section className="corporateNewsSection highlightedNewsSection">
            <div className="corporateNewsSectionHeader">
              <div>
                <p className="eyebrow">Stock Pool Focus</p>
                <h2>
                  <ShieldCheck size={20} aria-hidden="true" />
                  股票池重点关注
                </h2>
                <p>仅展示影响到当前市场股票池成分的回购或减持新闻。</p>
              </div>
              <strong>{highlightedStories.length} 个公司动态</strong>
            </div>
            {highlightedStories.length ? (
              <div className="corporateNewsGrid">
                {highlightedStories.map((story) => (
                  <NewsCard key={story.key} story={story} market={market} emphasized onOpenStock={onOpenStock} />
                ))}
              </div>
            ) : (
              <EmptySection>当前筛选范围内没有命中股票池的事件。</EmptySection>
            )}
          </section>

          <section className="corporateNewsSection">
            <div className="corporateNewsSectionHeader">
              <div>
                <p className="eyebrow">Market Feed</p>
                <h2>
                  <TrendingDown size={20} aria-hidden="true" />
                  市场其他动态
                </h2>
                <p>保留股票池外公司的事件，便于观察市场层面的资本动作。</p>
              </div>
              <strong>{regularStories.length} 个公司动态</strong>
            </div>
            {regularStories.length ? (
              <div className="corporateNewsGrid">
                {regularStories.map((story) => (
                  <NewsCard key={story.key} story={story} market={market} emphasized={false} onOpenStock={onOpenStock} />
                ))}
              </div>
            ) : (
              <EmptySection>当前筛选范围内没有其他市场事件。</EmptySection>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
