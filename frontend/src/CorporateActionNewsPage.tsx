import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Building2,
  CalendarDays,
  ExternalLink,
  Newspaper,
  RefreshCw,
  ShieldCheck,
  TrendingDown
} from "lucide-react";
import {
  fetchCorporateActionNews,
  type CorporateActionEventType,
  type CorporateActionNewsItem,
  type CorporateActionNewsResponse,
  type Market
} from "./api";

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

function groupStories(rows: CorporateActionNewsItem[]) {
  const grouped = new Map<string, CorporateActionNewsItem[]>();
  rows.forEach((row) => {
    const key = `${row.source_url}|${row.event_type}|${row.headline}|${row.published_at}`;
    grouped.set(key, [...(grouped.get(key) ?? []), row]);
  });
  return Array.from(grouped.entries()).map(([key, events]): NewsStory => {
    const lead = events.reduce((best, item) => {
      if (isPoolEvent(item) && !isPoolEvent(best)) return item;
      return item.summary_zh.length > best.summary_zh.length ? item : best;
    }, events[0]);
    return { key, lead, events, inStockPool: events.some(isPoolEvent) };
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

function storyFacts(story: NewsStory) {
  return Array.from(
    new Set(
      story.events.flatMap((event) =>
        [event.amount_text, event.quantity_text, event.ownership_change_text].filter((value) => value.trim())
      )
    )
  ).slice(0, 4);
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
  const title = lead.headline_zh || lead.headline;
  const showOriginalTitle = Boolean(lead.headline_zh && lead.headline_zh !== lead.headline);
  const stocks = affectedStocks(story.events, market);
  const facts = storyFacts(story);

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
        <a href={lead.source_url} target="_blank" rel="noreferrer">
          查看原文
          <ExternalLink size={13} aria-hidden="true" />
        </a>
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
            <span>公司事件</span>
            <strong>{response?.count ?? "--"}</strong>
          </div>
          <div className="highStat">
            <span>股票池命中</span>
            <strong>{response?.in_stock_pool_count ?? "--"}</strong>
          </div>
          <div>
            <span>股票池外</span>
            <strong>{response?.outside_stock_pool_count ?? "--"}</strong>
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
              <strong>{highlightedStories.length} 条新闻</strong>
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
              <strong>{regularStories.length} 条新闻</strong>
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
