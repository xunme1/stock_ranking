from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import COMPANY_PROFILES_FILE, RANKING_CACHE_DIR  # noqa: E402
from app.services.data_loader import normalize_ticker  # noqa: E402


OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def clean_float(value: Any, digits: int = 3) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits)


def load_company_profiles() -> dict[str, dict[str, Any]]:
    if not COMPANY_PROFILES_FILE.exists():
        return {}
    df = pd.read_csv(COMPANY_PROFILES_FILE)
    profiles: dict[str, dict[str, Any]] = {}
    for row in df.fillna("").itertuples(index=False):
        ticker = normalize_ticker(str(getattr(row, "ticker", "")))
        if not ticker:
            continue
        market_cap = clean_float(getattr(row, "market_cap", None), 0)
        profiles[ticker] = {
            "name": str(getattr(row, "name", "")).strip(),
            "market_cap": market_cap,
            "sic_description": str(getattr(row, "sic_description", "")).strip(),
        }
    return profiles


def load_latest_ranking(window: int, as_of_date: str | None) -> tuple[pd.DataFrame, str]:
    path = RANKING_CACHE_DIR / f"ranking_window_{window}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Ranking cache not found: {path}")
    df = pd.read_csv(path)
    df["as_of_date"] = df["as_of_date"].astype(str)
    df["ticker"] = df["ticker"].astype(str).map(normalize_ticker)
    for column in ["rank", "close", "atr_score", "price_change_3d_pct", "price_vs_center_pct", "excess_atr_vs_benchmark"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    dates = sorted(df["as_of_date"].dropna().unique().tolist())
    if as_of_date:
        dates = [item for item in dates if item <= as_of_date]
    if not dates:
        raise ValueError("No ranking date found")
    latest_date = dates[-1]
    return df[df["as_of_date"] == latest_date].copy().sort_values("rank"), latest_date


def build_cloud(window: int, as_of_date: str | None) -> dict[str, Any]:
    ranking, latest_date = load_latest_ranking(window, as_of_date)
    profiles = load_company_profiles()
    rows: list[dict[str, Any]] = []
    for row in ranking.itertuples(index=False):
        ticker = normalize_ticker(str(row.ticker))
        if ticker == "QQQ":
            continue
        profile = profiles.get(ticker, {})
        market_cap = profile.get("market_cap")
        # Fallback size keeps missing-market-cap names visible without dominating the map.
        size = market_cap if market_cap and market_cap > 0 else max(1, 120 - int(row.rank))
        rows.append(
            {
                "ticker": ticker,
                "name": profile.get("name", ""),
                "sector": str(getattr(row, "sector", "") or "Unknown"),
                "stock_type": str(getattr(row, "stock_type", "") or "Unknown"),
                "rank": int(row.rank),
                "has_options": str(getattr(row, "has_options", "U") or "U"),
                "close": clean_float(row.close, 2),
                "atr_score": clean_float(row.atr_score, 3),
                "price_change_3d_pct": clean_float(row.price_change_3d_pct, 2),
                "price_vs_center_pct": clean_float(row.price_vs_center_pct, 2),
                "excess_atr_vs_benchmark": clean_float(row.excess_atr_vs_benchmark, 3),
                "market_cap": market_cap,
                "size": size,
            }
        )

    sectors: list[dict[str, Any]] = []
    for sector, group in pd.DataFrame(rows).groupby("sector", dropna=False):
        items = group.sort_values("rank").to_dict(orient="records")
        sectors.append(
            {
                "sector": str(sector or "Unknown"),
                "count": len(items),
                "avg_atr_score": clean_float(group["atr_score"].mean(), 3),
                "avg_3d_change": clean_float(group["price_change_3d_pct"].mean(), 2),
                "top20_count": int((group["rank"] <= 20).sum()),
                "children": items,
            }
        )
    sectors.sort(key=lambda item: (item["avg_atr_score"] is None, -(item["avg_atr_score"] or -999)))

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window": window,
        "as_of_date": latest_date,
        "metric": "atr_score",
        "size": "market_cap",
        "sectors": sectors,
    }


def render_html(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>股票池板块云图实验</title>
  <style>
    :root {{
      --ink: #162033;
      --muted: #607089;
      --line: #d8e0eb;
      --bg: #f3f6fa;
      --panel: #ffffff;
      --blue: #1f6feb;
      --green: #08764f;
      --red: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
    }}
    .app {{
      min-height: 100vh;
      padding: 22px 28px 28px;
    }}
    header {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 18px;
    }}
    .eyebrow {{
      margin: 0 0 5px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 0;
      font-size: 30px;
      letter-spacing: 0;
    }}
    .toolbar {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }}
    select, button {{
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 0 12px;
      color: var(--ink);
      font: inherit;
      font-weight: 700;
    }}
    button.active {{
      border-color: var(--blue);
      background: #eaf2ff;
      color: var(--blue);
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 300px;
      gap: 16px;
      align-items: stretch;
    }}
    .cloudShell, .sidePanel {{
      min-height: 690px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      overflow: hidden;
      position: relative;
    }}
    #cloud {{
      min-height: 690px;
      height: 100%;
      position: relative;
    }}
    .tile {{
      position: absolute;
      border: 1px solid rgba(255,255,255,0.78);
      overflow: hidden;
      cursor: pointer;
      transition: transform 120ms ease, box-shadow 120ms ease;
    }}
    .tile:hover {{
      z-index: 5;
      transform: translateY(-1px);
      box-shadow: 0 10px 28px rgba(16, 24, 40, 0.22);
    }}
    .tileInner {{
      position: absolute;
      inset: 8px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 4px;
      min-width: 0;
      text-align: center;
    }}
    .ticker {{
      font-size: var(--ticker-size, 14px);
      font-weight: 900;
      color: #fff;
      text-shadow: 0 1px 2px rgba(0,0,0,0.28);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 100%;
    }}
    .meta {{
      color: rgba(255,255,255,0.88);
      font-size: var(--meta-size, 11px);
      font-weight: 800;
      text-shadow: 0 1px 2px rgba(0,0,0,0.25);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .sectorLabel {{
      position: absolute;
      left: 10px;
      top: 8px;
      z-index: 4;
      padding: 3px 7px;
      border-radius: 999px;
      background: rgba(255,255,255,0.82);
      color: var(--ink);
      font-size: 11px;
      font-weight: 900;
      pointer-events: none;
    }}
    .sidePanel {{
      padding: 16px;
    }}
    .legend {{
      display: grid;
      gap: 10px;
      margin-top: 14px;
    }}
    .legendItem {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      padding: 10px 0;
      border-bottom: 1px solid #edf1f6;
      font-size: 13px;
    }}
    .legendItem strong {{ font-size: 16px; }}
    .hint {{
      margin: 12px 0 0;
      color: var(--muted);
      line-height: 1.55;
      font-size: 13px;
    }}
    .tooltip {{
      position: fixed;
      z-index: 20;
      min-width: 230px;
      max-width: 310px;
      padding: 12px;
      background: rgba(22,32,51,0.95);
      color: #fff;
      border-radius: 10px;
      pointer-events: none;
      box-shadow: 0 16px 40px rgba(16,24,40,0.28);
      display: none;
      font-size: 12px;
    }}
    .tooltip h3 {{
      margin: 0 0 6px;
      font-size: 18px;
    }}
    .tooltip div {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      border-top: 1px solid rgba(255,255,255,0.16);
      padding-top: 5px;
      margin-top: 5px;
    }}
    @media (max-width: 980px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .cloudShell, #cloud {{ min-height: 620px; }}
      .sidePanel {{ min-height: auto; }}
    }}
  </style>
</head>
<body>
  <main class="app">
    <header>
      <div>
        <p class="eyebrow">Sector Cloud Experiment</p>
        <h1>股票池板块云图</h1>
        <p class="hint">窗口 <strong id="windowLabel"></strong>日 / 截止 <strong id="dateLabel"></strong>。面积默认按市值，颜色按 ATR 倍数或涨幅。</p>
      </div>
      <div class="toolbar">
        <select id="metricSelect" aria-label="颜色指标">
          <option value="atr_score">ATR倍数</option>
          <option value="price_change_3d_pct">较3日前</option>
          <option value="price_vs_center_pct">较重心</option>
          <option value="excess_atr_vs_benchmark">超额ATR</option>
        </select>
        <button type="button" class="active" data-size="market_cap">市值面积</button>
        <button type="button" data-size="equal">等权面积</button>
      </div>
    </header>
    <section class="layout">
      <div class="cloudShell">
        <div id="cloud"></div>
      </div>
      <aside class="sidePanel">
        <p class="eyebrow">How to Read</p>
        <h2>读图方式</h2>
        <p class="hint">每个方块是一只股票，方块按板块聚合。绿色表示指标为正，红色表示指标为负，颜色越深代表绝对值越大。点击股票可以跳转到正式详情页。</p>
        <div class="legend" id="sectorStats"></div>
      </aside>
    </section>
  </main>
  <div class="tooltip" id="tooltip"></div>
  <script>
    const CLOUD_DATA = {payload};

    const cloud = document.getElementById("cloud");
    const tooltip = document.getElementById("tooltip");
    const metricSelect = document.getElementById("metricSelect");
    const windowLabel = document.getElementById("windowLabel");
    const dateLabel = document.getElementById("dateLabel");
    const sectorStats = document.getElementById("sectorStats");
    let sizeMode = "market_cap";
    const SECTOR_CN = {{
      "Information Technology": "信息技术",
      "Communication Services": "通信服务",
      "Consumer Discretionary": "可选消费",
      "Consumer Staples": "日常消费",
      "Health Care": "医疗保健",
      "Financials": "金融",
      "Industrials": "工业",
      "Energy": "能源",
      "Utilities": "公用事业",
      "Materials": "材料",
      "Real Estate": "房地产",
      "ETF": "ETF",
      "Unknown": "其他"
    }};

    windowLabel.textContent = CLOUD_DATA.window;
    dateLabel.textContent = CLOUD_DATA.as_of_date;

    function sectorName(sector) {{
      return SECTOR_CN[sector] || sector || "其他";
    }}

    function flattenItems() {{
      return CLOUD_DATA.sectors.flatMap(sector => sector.children.map(item => ({{ ...item, sector: sector.sector }})));
    }}

    function colorFor(value, maxAbs) {{
      const v = Number(value || 0);
      const ratio = Math.min(Math.abs(v) / Math.max(maxAbs, 0.01), 1);
      const alpha = 0.25 + ratio * 0.72;
      if (v >= 0) return `rgba(8, 118, 79, ${{alpha}})`;
      return `rgba(180, 35, 24, ${{alpha}})`;
    }}

    function fmt(value, digits = 2, suffix = "") {{
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
      return `${{Number(value).toFixed(digits)}}${{suffix}}`;
    }}

    function fontSizesForTile(tile) {{
      const area = Math.max(tile.w * tile.h, 1);
      const base = Math.sqrt(area);
      const tickerSize = Math.max(9, Math.min(30, base / 8));
      const metaSize = Math.max(8, Math.min(15, base / 15));
      return {{ tickerSize, metaSize }};
    }}

    function metricText(item, metric) {{
      const suffix = metric.includes("pct") ? "%" : "";
      const digits = metric.includes("pct") ? 1 : 2;
      return fmt(item[metric], digits, suffix);
    }}

    function binaryTreemap(items, x, y, w, h, sizeKey) {{
      const total = items.reduce((sum, item) => sum + Number(item[sizeKey] || 1), 0) || 1;
      if (items.length === 1) return [{{ ...items[0], x, y, w, h }}];
      const sorted = [...items].sort((a, b) => Number(b[sizeKey] || 1) - Number(a[sizeKey] || 1));
      let acc = 0;
      let split = 1;
      for (; split < sorted.length; split += 1) {{
        const next = acc + Number(sorted[split - 1][sizeKey] || 1);
        if (next >= total / 2) {{
          acc = next;
          break;
        }}
        acc = next;
      }}
      const first = sorted.slice(0, split);
      const second = sorted.slice(split);
      const firstTotal = first.reduce((sum, item) => sum + Number(item[sizeKey] || 1), 0) || 1;
      const ratio = firstTotal / total;
      if (!second.length) return [{{ ...first[0], x, y, w, h }}];
      if (w >= h) {{
        const w1 = w * ratio;
        return [
          ...binaryTreemap(first, x, y, w1, h, sizeKey),
          ...binaryTreemap(second, x + w1, y, w - w1, h, sizeKey)
        ];
      }}
      const h1 = h * ratio;
      return [
        ...binaryTreemap(first, x, y, w, h1, sizeKey),
        ...binaryTreemap(second, x, y + h1, w, h - h1, sizeKey)
      ];
    }}

    function renderStats() {{
      sectorStats.innerHTML = "";
      CLOUD_DATA.sectors.slice(0, 10).forEach(sector => {{
        const div = document.createElement("div");
        div.className = "legendItem";
        div.innerHTML = `<span>${{sectorName(sector.sector)}}<br><small>${{sector.count}}只 / 前20 ${{sector.top20_count}}只</small></span><strong>${{fmt(sector.avg_atr_score, 2)}}</strong>`;
        sectorStats.appendChild(div);
      }});
    }}

    function render() {{
      cloud.innerHTML = "";
      const metric = metricSelect.value;
      const items = flattenItems().map(item => ({{
        ...item,
        renderSize: sizeMode === "equal" ? 1 : Number(item.market_cap || item.size || 1)
      }}));
      const maxAbs = Math.max(...items.map(item => Math.abs(Number(item[metric] || 0))), 0.01);
      const rect = cloud.getBoundingClientRect();
      const sectors = CLOUD_DATA.sectors.map(sector => ({{
        ...sector,
        renderSize: sector.children.reduce((sum, item) => sum + (sizeMode === "equal" ? 1 : Number(item.market_cap || item.size || 1)), 0)
      }}));
      const sectorRects = binaryTreemap(sectors, 0, 0, rect.width, rect.height, "renderSize");
      sectorRects.forEach(sectorRect => {{
        const label = document.createElement("div");
        label.className = "sectorLabel";
        label.textContent = sectorName(sectorRect.sector);
        label.style.left = `${{sectorRect.x + 8}}px`;
        label.style.top = `${{sectorRect.y + 8}}px`;
        cloud.appendChild(label);
        const children = sectorRect.children.map(item => ({{
          ...item,
          renderSize: sizeMode === "equal" ? 1 : Number(item.market_cap || item.size || 1)
        }}));
        const tiles = binaryTreemap(children, sectorRect.x, sectorRect.y, sectorRect.w, sectorRect.h, "renderSize");
        tiles.forEach(tile => {{
          if (tile.w < 16 || tile.h < 16) return;
          const div = document.createElement("div");
          div.className = "tile";
          div.style.left = `${{tile.x}}px`;
          div.style.top = `${{tile.y}}px`;
          div.style.width = `${{Math.max(tile.w, 0)}}px`;
          div.style.height = `${{Math.max(tile.h, 0)}}px`;
          div.style.background = colorFor(tile[metric], maxAbs);
          const sizes = fontSizesForTile(tile);
          div.style.setProperty("--ticker-size", `${{sizes.tickerSize}}px`);
          div.style.setProperty("--meta-size", `${{sizes.metaSize}}px`);
          const showMeta = tile.w > 44 && tile.h > 36;
          div.innerHTML = `<div class="tileInner"><div class="ticker">${{tile.ticker}}</div>${{showMeta ? `<div class="meta">${{metricText(tile, metric)}}</div>` : ""}}</div>`;
          div.addEventListener("mousemove", event => showTooltip(event, tile, metric));
          div.addEventListener("mouseleave", () => tooltip.style.display = "none");
          div.addEventListener("click", () => {{
            window.location.href = `/stocks/${{tile.ticker}}?date=${{CLOUD_DATA.as_of_date}}`;
          }});
          cloud.appendChild(div);
        }});
      }});
    }}

    function showTooltip(event, item, metric) {{
      tooltip.style.display = "block";
      tooltip.style.left = `${{Math.min(event.clientX + 14, window.innerWidth - 330)}}px`;
      tooltip.style.top = `${{Math.min(event.clientY + 14, window.innerHeight - 210)}}px`;
      tooltip.innerHTML = `
        <h3>${{item.ticker}}</h3>
        <p>${{item.name || item.stock_type || ""}}</p>
        <div><span>板块</span><strong>${{sectorName(item.sector)}}</strong></div>
        <div><span>排名</span><strong>#${{item.rank}}</strong></div>
        <div><span>ATR倍数</span><strong>${{fmt(item.atr_score, 3)}}</strong></div>
        <div><span>较3日前</span><strong>${{fmt(item.price_change_3d_pct, 2, "%")}}</strong></div>
        <div><span>较重心</span><strong>${{fmt(item.price_vs_center_pct, 2, "%")}}</strong></div>
        <div><span>有无期权</span><strong>${{item.has_options}}</strong></div>
      `;
    }}

    metricSelect.addEventListener("change", render);
    document.querySelectorAll("button[data-size]").forEach(button => {{
      button.addEventListener("click", () => {{
        sizeMode = button.dataset.size;
        document.querySelectorAll("button[data-size]").forEach(item => item.classList.toggle("active", item === button));
        render();
      }});
    }});
    window.addEventListener("resize", render);
    renderStats();
    render();
  </script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate standalone sector cloud experiment.")
    parser.add_argument("--window", type=int, default=10, choices=[10, 20], help="Ranking window.")
    parser.add_argument("--as-of-date", default=None, help="Use cached date on or before YYYY-MM-DD.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = build_cloud(args.window, args.as_of_date)
    data_path = OUTPUT_DIR / f"sector_cloud_{data['as_of_date']}_w{args.window}.json"
    html_path = OUTPUT_DIR / f"index_w{args.window}.html"
    latest_html_path = OUTPUT_DIR / "index.html"
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html(data), encoding="utf-8")
    latest_html_path.write_text(render_html(data), encoding="utf-8")
    print(f"Sector cloud data written: {data_path}")
    print(f"Sector cloud page written: {html_path}")
    print(f"Latest sector cloud page written: {latest_html_path}")


if __name__ == "__main__":
    main()
