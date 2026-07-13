#!/usr/bin/env python3
"""Generate a standalone, interactive market daily brief HTML from a JSON file.

Usage:
    python generate_daily_brief.py input.json
    python generate_daily_brief.py input.json -o report.html
    python generate_daily_brief.py input.json -o report.html --theme light

The generated HTML is fully offline: JSON, CSS and JavaScript are embedded.
Technology-focus sections are included only when technology_focus contains data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

TEMPLATE = r"""<!doctype html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>市场量化动能日报</title>
<style>
:root{
  --bg:#07111f;--bg2:#0b1728;--panel:rgba(16,31,52,.82);--panel2:rgba(20,39,64,.72);
  --text:#eef5ff;--muted:#91a4bd;--line:rgba(151,174,205,.16);--accent:#7c8cff;
  --accent2:#2dd4bf;--up:#34d399;--down:#fb7185;--warn:#fbbf24;--shadow:0 22px 55px rgba(0,0,0,.28);
  --hero:radial-gradient(circle at 12% 10%,rgba(124,140,255,.22),transparent 30%),radial-gradient(circle at 88% 20%,rgba(45,212,191,.14),transparent 26%),linear-gradient(180deg,#081321 0%,#07111f 55%,#07101d 100%);
}
html[data-theme="light"]{
  --bg:#f3f7fb;--bg2:#eaf0f7;--panel:rgba(255,255,255,.88);--panel2:rgba(248,251,255,.94);
  --text:#102033;--muted:#61728a;--line:rgba(42,65,94,.14);--accent:#5665df;
  --accent2:#0f9f91;--up:#139b68;--down:#d64b65;--warn:#b87900;--shadow:0 20px 48px rgba(49,70,98,.12);
  --hero:radial-gradient(circle at 12% 10%,rgba(86,101,223,.13),transparent 30%),radial-gradient(circle at 88% 20%,rgba(15,159,145,.10),transparent 26%),linear-gradient(180deg,#f8fbff 0%,#f3f7fb 62%,#eef4fa 100%);
}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--hero);color:var(--text);font-family:Inter,"SF Pro Display","PingFang SC","Microsoft YaHei",system-ui,-apple-system,sans-serif;line-height:1.55;min-height:100vh}
body:before{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(rgba(255,255,255,.018) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.018) 1px,transparent 1px);background-size:34px 34px;mask-image:linear-gradient(to bottom,black,transparent 75%)}
a{color:inherit}.shell{width:min(1480px,calc(100% - 32px));margin:0 auto;padding:24px 0 60px;position:relative}.topbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:22px}.brand{display:flex;align-items:center;gap:12px}.brand-mark{width:42px;height:42px;border-radius:14px;background:linear-gradient(135deg,var(--accent),var(--accent2));display:grid;place-items:center;box-shadow:0 12px 30px rgba(92,112,255,.28);font-weight:900;color:white;letter-spacing:-1px}.brand-title{font-weight:780;font-size:17px}.brand-sub{font-size:12px;color:var(--muted)}.actions{display:flex;gap:9px}.icon-btn,.tab-btn,.filter-btn,.select,.search{border:1px solid var(--line);background:var(--panel);color:var(--text);border-radius:12px;backdrop-filter:blur(18px)}.icon-btn{height:40px;padding:0 14px;cursor:pointer;font-weight:680}.icon-btn:hover,.tab-btn:hover,.filter-btn:hover{border-color:rgba(124,140,255,.5);transform:translateY(-1px)}
.hero{position:relative;overflow:hidden;padding:32px;border-radius:28px;border:1px solid var(--line);background:linear-gradient(125deg,rgba(26,48,80,.9),rgba(12,29,49,.74));box-shadow:var(--shadow);margin-bottom:18px}.hero:after{content:"";position:absolute;width:360px;height:360px;border-radius:50%;right:-110px;top:-160px;background:radial-gradient(circle,rgba(124,140,255,.34),transparent 67%)}html[data-theme="light"] .hero{background:linear-gradient(125deg,rgba(255,255,255,.94),rgba(241,247,255,.90))}.eyebrow{display:flex;align-items:center;gap:10px;color:var(--accent2);text-transform:uppercase;font-size:12px;font-weight:800;letter-spacing:.14em}.live-dot{width:8px;height:8px;border-radius:50%;background:var(--up);box-shadow:0 0 0 6px rgba(52,211,153,.10)}h1{font-size:clamp(30px,5vw,54px);line-height:1.08;letter-spacing:-.045em;margin:14px 0 12px;max-width:780px}.hero-desc{color:var(--muted);max-width:820px;font-size:15px;margin:0}.hero-meta{display:flex;flex-wrap:wrap;gap:10px;margin-top:22px}.chip{display:inline-flex;align-items:center;gap:7px;padding:8px 11px;border-radius:999px;background:rgba(125,145,180,.10);border:1px solid var(--line);font-size:12px;color:var(--muted)}.chip b{color:var(--text)}
.kpi-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin:18px 0}.card{background:var(--panel);border:1px solid var(--line);border-radius:20px;box-shadow:0 12px 32px rgba(0,0,0,.11);backdrop-filter:blur(16px)}.kpi{padding:18px;min-height:132px;position:relative;overflow:hidden}.kpi:after{content:"";position:absolute;right:-25px;bottom:-35px;width:100px;height:100px;border-radius:50%;background:var(--kpi-glow,rgba(124,140,255,.12))}.kpi-label{font-size:12px;color:var(--muted);font-weight:720}.kpi-value{font-size:31px;font-weight:820;letter-spacing:-.04em;margin-top:11px}.kpi-note{font-size:12px;color:var(--muted);margin-top:4px}.kpi-note strong{color:var(--text)}
.grid-main{display:grid;grid-template-columns:minmax(0,1.62fr) minmax(320px,.78fr);gap:18px}.grid-main>*{min-width:0}.stack{display:grid;grid-template-columns:minmax(0,1fr);gap:18px;min-width:0}.section{padding:22px}.section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:18px}.section-title{font-size:18px;font-weight:790;letter-spacing:-.02em}.section-sub{font-size:12px;color:var(--muted);margin-top:3px}.tag{font-size:11px;padding:5px 8px;border-radius:8px;background:rgba(124,140,255,.11);color:#aeb8ff;border:1px solid rgba(124,140,255,.18);font-weight:750}html[data-theme="light"] .tag{color:#4e5bc4}
.insight-list{display:grid;gap:10px}.insight{display:grid;grid-template-columns:34px 1fr;gap:12px;padding:13px;border:1px solid var(--line);background:var(--panel2);border-radius:14px}.insight-index{width:30px;height:30px;border-radius:10px;display:grid;place-items:center;background:linear-gradient(135deg,rgba(124,140,255,.20),rgba(45,212,191,.13));font-size:12px;font-weight:800}.insight-text{font-size:13px;color:var(--muted)}
.benchmark{padding:22px;position:relative;overflow:hidden}.benchmark-top{display:flex;align-items:flex-start;justify-content:space-between}.ticker{font-size:26px;font-weight:850;letter-spacing:-.03em}.name{font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.rank-orb{width:72px;height:72px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(var(--accent) var(--rank-angle),rgba(127,148,180,.13) 0);position:relative}.rank-orb:before{content:"";position:absolute;inset:7px;border-radius:50%;background:var(--bg2)}.rank-orb span{position:relative;font-size:13px;font-weight:800}.metric-row{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:18px}.mini-metric{padding:12px;border-radius:13px;background:var(--panel2);border:1px solid var(--line)}.mini-label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}.mini-value{font-size:18px;font-weight:790;margin-top:4px}.positive{color:var(--up)!important}.negative{color:var(--down)!important}.neutral{color:var(--muted)!important}
.leader-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.leader{padding:15px;border-radius:16px;background:var(--panel2);border:1px solid var(--line);position:relative;overflow:hidden}.leader-rank{position:absolute;right:12px;top:9px;font-size:38px;font-weight:900;color:rgba(130,151,185,.13)}.leader-ticker{font-size:19px;font-weight:840}.leader-type{font-size:11px;color:var(--muted);margin-top:2px}.leader-score{font-size:25px;font-weight:840;margin:13px 0 3px}.leader-footer{display:flex;justify-content:space-between;font-size:11px;color:var(--muted)}
.bar-list{display:grid;gap:12px}.bar-row{display:grid;grid-template-columns:minmax(95px,1fr) 2.2fr 48px;align-items:center;gap:10px}.bar-label{font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.bar-track{height:8px;border-radius:999px;background:rgba(127,148,180,.13);overflow:hidden}.bar-fill{height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--accent),var(--accent2));width:0;transition:width .7s ease}.bar-value{text-align:right;font-size:11px;color:var(--muted)}
.ai-copy{font-size:13px;color:var(--muted)}.ai-block{padding:14px 0;border-top:1px solid var(--line)}.ai-block:first-child{border-top:0;padding-top:0}.ai-heading{font-size:13px;font-weight:780;color:var(--text);margin-bottom:5px}.ai-meta{display:flex;gap:8px;flex-wrap:wrap;margin-top:15px}
.movers{display:grid;grid-template-columns:1fr 1fr;gap:14px}.mover-col{border-radius:16px;border:1px solid var(--line);background:var(--panel2);padding:14px}.mover-title{display:flex;justify-content:space-between;align-items:center;font-size:13px;font-weight:770;margin-bottom:8px}.mover-list{display:grid}.mover{display:grid;grid-template-columns:38px 1fr auto;align-items:center;gap:8px;padding:10px 0;border-top:1px solid var(--line)}.mover:first-child{border-top:0}.mover-rank{font-size:11px;color:var(--muted)}.mover-symbol{font-size:13px;font-weight:800}.mover-meta{font-size:10px;color:var(--muted)}.mover-change{text-align:right;font-size:12px;font-weight:800}.mover-rankchange{font-size:10px;color:var(--muted);font-weight:600}
.tabs{display:flex;gap:8px;flex-wrap:wrap}.tab-btn,.filter-btn{padding:8px 11px;font-size:12px;cursor:pointer;font-weight:710}.tab-btn.active,.filter-btn.active{background:linear-gradient(135deg,var(--accent),#6675ef);border-color:transparent;color:white;box-shadow:0 8px 22px rgba(92,112,255,.22)}.table-tools{display:flex;justify-content:space-between;gap:12px;margin-bottom:12px;flex-wrap:wrap}.search{padding:9px 12px;outline:none;min-width:230px}.search:focus,.select:focus{border-color:rgba(124,140,255,.55)}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:15px}.data-table{width:100%;border-collapse:collapse;min-width:1020px;font-size:12px}.data-table th{position:sticky;top:0;z-index:2;background:color-mix(in srgb,var(--bg2) 92%,transparent);color:var(--muted);text-align:right;padding:12px 11px;border-bottom:1px solid var(--line);font-size:10px;text-transform:uppercase;letter-spacing:.05em;cursor:pointer}.data-table th:nth-child(2),.data-table th:nth-child(3),.data-table th:nth-child(4){text-align:left}.data-table td{padding:11px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}.data-table tr:last-child td{border-bottom:0}.data-table tr:hover td{background:rgba(124,140,255,.045)}.data-table td:nth-child(2),.data-table td:nth-child(3),.data-table td:nth-child(4){text-align:left}.rank-badge{display:inline-grid;place-items:center;min-width:29px;height:25px;border-radius:8px;background:rgba(124,140,255,.10);font-weight:780}.symbol-cell{font-weight:820;font-size:13px}.type-pill{display:inline-flex;padding:4px 7px;border-radius:7px;background:rgba(45,212,191,.08);color:var(--accent2);border:1px solid rgba(45,212,191,.12);font-size:10px}.rank-up:before{content:"▲ ";font-size:8px}.rank-down:before{content:"▼ ";font-size:8px}
.chart-area{height:270px;position:relative}.chart-svg{width:100%;height:100%;overflow:visible}.chart-grid{stroke:var(--line);stroke-width:1}.chart-line{fill:none;stroke:url(#lineGradient);stroke-width:3;stroke-linecap:round;stroke-linejoin:round}.chart-dot{fill:var(--panel);stroke:var(--accent2);stroke-width:2}.chart-axis{fill:var(--muted);font-size:10px}.chart-caption{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.select{padding:8px 10px;outline:none}.spark{width:80px;height:26px}.spark-line{fill:none;stroke:var(--accent);stroke-width:2}.spark-dot{fill:var(--accent2)}
.tech-grid{display:grid;grid-template-columns:.8fr 1.2fr;gap:14px}.big-stat{padding:20px;border-radius:17px;background:linear-gradient(135deg,rgba(124,140,255,.14),rgba(45,212,191,.08));border:1px solid var(--line)}.big-stat-value{font-size:44px;font-weight:870;letter-spacing:-.05em}.big-stat-label{font-size:12px;color:var(--muted)}.watch-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:9px}.watch{padding:11px;border:1px solid var(--line);background:var(--panel2);border-radius:12px;display:flex;align-items:center;justify-content:space-between}.watch b{font-size:12px}.watch span{font-size:11px;color:var(--muted)}
.footer{margin-top:22px;color:var(--muted);font-size:11px;display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap;padding:0 4px}.empty{padding:30px;text-align:center;color:var(--muted)}
@media(max-width:1120px){.kpi-grid{grid-template-columns:repeat(3,1fr)}.grid-main{grid-template-columns:1fr}.leader-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:760px){.shell{width:min(100% - 20px,1480px);padding-top:12px}.topbar{align-items:flex-start}.brand-sub{display:none}.hero{padding:24px 20px;border-radius:22px}.kpi-grid{grid-template-columns:repeat(2,1fr);gap:10px}.kpi{min-height:116px;padding:15px}.grid-main{gap:12px}.section,.benchmark{padding:17px}.leader-grid{grid-template-columns:1fr}.movers,.tech-grid{grid-template-columns:1fr}.watch-grid{grid-template-columns:1fr}.section-head{flex-direction:column}.table-tools{align-items:stretch}.search{width:100%}.actions .icon-btn:first-child{display:none}.bar-row{grid-template-columns:88px 1fr 42px}.kpi-value{font-size:27px}}
@media(max-width:480px){.kpi-grid{grid-template-columns:1fr}.hero-meta{gap:7px}.chip{padding:7px 9px}.metric-row{grid-template-columns:1fr 1fr}.section-title{font-size:17px}}
@media print{body{background:white;color:#111}.shell{width:100%;padding:0}.actions,.tabs,.table-tools,.footer .interactive-only{display:none!important}.card,.hero{box-shadow:none;break-inside:avoid;background:white;border-color:#ddd}.grid-main{grid-template-columns:1fr}.section{break-inside:avoid}.data-table th{position:static;background:#f4f4f4}.table-wrap{overflow:visible}.data-table{min-width:0;font-size:9px}.data-table td,.data-table th{padding:7px 5px}}

.section-actions,.mover-head-actions{display:flex;align-items:center;gap:9px}.view-toggle{border:1px solid var(--line);background:rgba(124,140,255,.08);color:var(--text);border-radius:10px;padding:6px 9px;font-size:11px;font-weight:760;cursor:pointer;white-space:nowrap;transition:.18s ease}.view-toggle:hover{border-color:rgba(124,140,255,.55);transform:translateY(-1px)}.view-toggle.active{color:white;border-color:transparent;background:linear-gradient(135deg,var(--accent),#6675ef);box-shadow:0 7px 18px rgba(92,112,255,.22)}
.mover-col{min-width:0}.mover-viewport{height:420px;overflow:auto;padding-right:5px}.main-table-viewport,.main-industry-view{height:560px;overflow:auto}.hidden{display:none!important}.scroll-zone{scrollbar-width:thin;scrollbar-color:rgba(124,140,255,.55) rgba(127,148,180,.10)}.scroll-zone::-webkit-scrollbar{width:9px;height:9px}.scroll-zone::-webkit-scrollbar-track{background:rgba(127,148,180,.08);border-radius:999px}.scroll-zone::-webkit-scrollbar-thumb{background:linear-gradient(var(--accent),var(--accent2));border-radius:999px;border:2px solid transparent;background-clip:padding-box}
.industry-panel{min-height:100%;padding:7px 2px}.industry-overview{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;padding:11px 12px 14px;border-bottom:1px solid var(--line);margin-bottom:4px}.industry-total{font-size:24px;font-weight:850;letter-spacing:-.04em}.industry-caption{font-size:11px;color:var(--muted)}.industry-row{padding:13px 10px;border-bottom:1px solid var(--line)}.industry-row:last-child{border-bottom:0}.industry-row-top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px}.industry-name{font-size:12px;font-weight:760;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.industry-value{font-size:11px;color:var(--muted);white-space:nowrap}.industry-track{height:8px;border-radius:999px;background:rgba(127,148,180,.13);overflow:hidden}.industry-fill{height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--accent),var(--accent2));transform-origin:left;animation:growBar .55s ease both}.industry-note{padding:11px 10px;color:var(--muted);font-size:10px;line-height:1.65}.main-industry-view{border:1px solid var(--line);border-radius:15px;padding:12px 15px}.main-industry-view .industry-row{padding-left:4px;padding-right:4px}@keyframes growBar{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@media(max-width:760px){.section-actions{width:100%;justify-content:space-between}.mover-viewport{height:390px}.main-table-viewport,.main-industry-view{height:520px}.mover-head-actions{gap:6px}.view-toggle{padding:6px 8px}}
@media print{.view-toggle{display:none!important}.mover-viewport,.main-table-viewport,.main-industry-view{height:auto!important;overflow:visible!important}.hidden{display:none!important}}

</style>
</head>
<body>
<div class="shell">
  <header class="topbar">
    <div class="brand"><div class="brand-mark">Q</div><div><div class="brand-title">QuantScope Daily</div><div class="brand-sub">Market Momentum Intelligence</div></div></div>
    <div class="actions"><button class="icon-btn" id="printBtn">打印 / PDF</button><button class="icon-btn" id="themeBtn">切换主题</button></div>
  </header>

  <section class="hero">
    <div class="eyebrow"><span class="live-dot"></span><span id="marketEyebrow">市场 · 收盘后量化观察</span></div>
    <h1>市场动能日报</h1>
    <p class="hero-desc">基于 10 个交易日排名、ATR 动能、价格相对重心、短期涨幅与榜单迁移，快速识别强势延续、结构轮动与异常变化。</p>
    <div class="hero-meta">
      <span class="chip">报告日期 <b id="reportDate">—</b></span>
      <span class="chip">比较基准 <b id="benchmarkLabel">—</b></span>
      <span class="chip">观察窗口 <b id="windowLabel">—</b></span>
      <span class="chip">生成时间 <b id="generatedAt">—</b></span>
    </div>
  </section>

  <section class="kpi-grid" id="kpiGrid"></section>

  <div class="grid-main">
    <main class="stack">
      <section class="card section">
        <div class="section-head"><div><div class="section-title">今日核心结论</div><div class="section-sub">从榜单变化中提炼最值得先看的信息</div></div><span class="tag">EXECUTIVE SUMMARY</span></div>
        <div class="insight-list" id="summaryList"></div>
      </section>

      <section class="card section">
        <div class="section-head"><div><div class="section-title">强势领跑</div><div class="section-sub">ATR 动能排名前三与关键价格位置</div></div><span class="tag">TOP LEADERS</span></div>
        <div class="leader-grid" id="leaderGrid"></div>
      </section>

      <section class="card section">
        <div class="section-head"><div><div class="section-title">榜单异动雷达</div><div class="section-sub">同时观察单日涨跌与排名迁移，避免只看价格</div></div><span class="tag">MOMENTUM</span></div>
        <div class="movers">
          <div class="mover-col">
            <div class="mover-title"><span class="positive">强势上行</span><div class="mover-head-actions"><span id="upCount"></span><button class="view-toggle" id="upViewToggle" type="button">行业占比</button></div></div>
            <div class="mover-viewport scroll-zone"><div class="mover-list" id="upList"></div><div class="industry-panel hidden" id="upIndustry"></div></div>
          </div>
          <div class="mover-col">
            <div class="mover-title"><span class="negative">快速走弱</span><div class="mover-head-actions"><span id="downCount"></span><button class="view-toggle" id="downViewToggle" type="button">行业占比</button></div></div>
            <div class="mover-viewport scroll-zone"><div class="mover-list" id="downList"></div><div class="industry-panel hidden" id="downIndustry"></div></div>
          </div>
        </div>
      </section>

      <section class="card section">
        <div class="section-head"><div><div class="section-title">股票排名明细</div><div class="section-sub">支持切换数据集、搜索、排序及榜单行业占比查看</div></div><div class="section-actions"><button class="view-toggle" id="mainViewToggle" type="button">行业占比</button><span class="tag">INTERACTIVE TABLE</span></div></div>
        <div class="table-tools"><div class="tabs" id="tableTabs"><button class="tab-btn active" data-mode="top20">当前 Top20</button><button class="tab-btn" data-mode="stable_top20">稳定 Top20</button><button class="tab-btn" data-mode="entered_top20">新进入</button><button class="tab-btn" data-mode="dropped_top20">跌出 Top20</button><button class="tab-btn" id="techTableTab" data-mode="technology_focus.top10">科技 Top10</button></div><input class="search" id="tableSearch" placeholder="搜索代码、名称或类型…"></div>
        <div class="table-wrap main-table-viewport scroll-zone" id="mainTableWrap"><table class="data-table"><thead id="tableHead"></thead><tbody id="tableBody"></tbody></table></div><div class="industry-panel main-industry-view scroll-zone hidden" id="mainIndustryView"></div>
      </section>

      <section class="card section">
        <div class="section-head"><div><div class="section-title">10 日排名轨迹</div><div class="section-sub">排名数字越小越强，纵轴已做反向处理</div></div><span class="tag">RANK HISTORY</span></div>
        <div class="chart-caption"><div id="chartSummary" class="section-sub"></div><select class="select" id="rankTicker"></select></div>
        <div class="chart-area" id="rankChart"></div>
      </section>
    </main>

    <aside class="stack">
      <section class="card benchmark" id="benchmarkCard"></section>

      <section class="card section">
        <div class="section-head"><div><div class="section-title">前20 类型结构</div><div class="section-sub">当前强势队列的行业风格</div></div><span class="tag">COMPOSITION</span></div>
        <div class="bar-list" id="typeBars"></div>
      </section>

      <section class="card section">
        <div class="section-head"><div><div class="section-title">模型解读</div><div class="section-sub">基于当前量化结果自动生成</div></div><span class="tag">AI INTERPRETATION</span></div>
        <div class="ai-copy" id="aiCopy"></div><div class="ai-meta" id="aiMeta"></div>
      </section>

      <section class="card section" id="techSection">
        <div class="section-head"><div><div class="section-title">科技专项</div><div class="section-sub">科技相关股票的广度与领涨方向</div></div><span class="tag">TECH FOCUS</span></div>
        <div class="tech-grid"><div class="big-stat"><div class="big-stat-value" id="techCount">—</div><div class="big-stat-label">科技观察池股票</div><div class="kpi-note"><strong id="techTop20">—</strong> 只位于总榜前20</div></div><div class="bar-list" id="techBars"></div></div>
        <div class="section-sub" style="margin:16px 0 8px">重点观察</div><div class="watch-grid" id="techWatch"></div>
      </section>

      <section class="card section">
        <div class="section-head"><div><div class="section-title">稳定强势队列</div><div class="section-sub">最近 5 个交易日维持在前20</div></div><span class="tag">PERSISTENCE</span></div>
        <div class="watch-grid" id="stableWatch"></div>
      </section>
    </aside>
  </div>

  <footer class="footer"><span>数据来源：本地量化日报 JSON · 指标仅用于研究与观察，不构成投资建议。</span><span class="interactive-only">单文件离线页面 · 可直接浏览、打印或另存为 PDF</span></footer>
</div>
<script id="reportData" type="application/json">__REPORT_JSON__</script>
<script>
const D=JSON.parse(document.getElementById('reportData').textContent);
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const esc=v=>String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const pathGet=(obj,path)=>String(path).split('.').reduce((o,k)=>o?.[k],obj);
const num=v=>Number.isFinite(Number(v))?Number(v):null;
const fmt=(v,d=2)=>num(v)===null?'—':Number(v).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d});
const pct=(v,d=2)=>num(v)===null?'—':`${Number(v)>0?'+':''}${fmt(v,d)}%`;
const signed=v=>num(v)===null?'—':`${Number(v)>0?'+':''}${Number(v)}`;
const cls=v=>num(v)===null?'neutral':Number(v)>0?'positive':Number(v)<0?'negative':'neutral';
const currencyPrefix=()=>D.market==='us'?'$':D.market==='hk'?'HK$':'';
const price=v=>num(v)===null?'—':`${currencyPrefix()}${fmt(v,2)}`;
const hasTech=()=>{const t=D.technology_focus||{};return Number(t.count||0)>0||['top10','strong_up','industry_distribution'].some(k=>Array.isArray(t[k])&&t[k].length>0)};

function renderMeta(){
  const market=D.market_label||D.market||'市场';
  document.title=`${market}量化动能日报 · ${D.as_of_date||''}`;
  $('#marketEyebrow').textContent=`${market} · 收盘后量化观察`;
  $('#reportDate').textContent=D.as_of_date||'—';
  $('#benchmarkLabel').textContent=D.benchmark_label||D.benchmark?.display||D.benchmark?.ticker||'—';
  $('#windowLabel').textContent=`${D.window||D.recent_dates?.length||'—'} 日`;
  $('#generatedAt').textContent=String(D.generated_at||'—').replace('T',' ');
  const h1=document.querySelector('h1'); if(h1)h1.textContent=`${market}市场动能日报`;
  const desc=document.querySelector('.hero-desc'); if(desc)desc.textContent=`基于 ${D.window||D.recent_dates?.length||'多'} 个交易日排名、ATR 动能、价格相对重心、短期涨幅与榜单迁移，快速识别强势延续、结构轮动与异常变化。`;
}
function renderKPIs(){
  const top=D.top20||[]; const avgDaily=top.length?top.reduce((s,x)=>s+Number(x.daily_change_pct||0),0)/top.length:0;
  const positive=top.filter(x=>Number(x.daily_change_pct)>0).length; const positiveRate=top.length?positive/top.length*100:0;
  const cards=[
    ['基准排名',`#${D.benchmark?.rank??'—'}`,`${D.benchmark_label||D.benchmark?.ticker||'基准'} · ATR ${fmt(D.benchmark?.atr_score,3)}`,'rgba(124,140,255,.16)'],
    ['稳定前20',`${D.stable_top20?.length||0} 只`,`5日持续强势队列`,'rgba(45,212,191,.15)'],
    ['榜单换手',`${D.entered_top20?.length||0}/${D.dropped_top20?.length||0}`,`进入 / 跌出 Top20`,'rgba(251,191,36,.14)'],
    ['Top20 平均涨幅',pct(avgDaily),`${positive} 只收涨，${Math.max(0,top.length-positive)} 只非涨`,'rgba(52,211,153,.14)']
  ];
  if(hasTech()) cards.push(['科技前20覆盖',`${D.technology_focus?.top20_count||0} 只`,`科技池共 ${D.technology_focus?.count||0} 只`,'rgba(251,113,133,.12)']);
  else cards.push(['Top20 收涨率',`${fmt(positiveRate,1)}%`,`${positive} / ${top.length||0} 只收涨`,'rgba(251,113,133,.12)']);
  $('#kpiGrid').innerHTML=cards.map(c=>`<article class="card kpi" style="--kpi-glow:${c[3]}"><div class="kpi-label">${c[0]}</div><div class="kpi-value ${String(c[1]).includes('%')?cls(parseFloat(c[1])):''}">${c[1]}</div><div class="kpi-note">${c[2]}</div></article>`).join('');
}
function renderSummary(){
  const rows=D.summary_points||[];
  $('#summaryList').innerHTML=rows.length?rows.map((s,i)=>`<div class="insight"><div class="insight-index">${String(i+1).padStart(2,'0')}</div><div class="insight-text">${esc(s)}</div></div>`).join(''):'<div class="empty">暂无核心结论</div>';
}
function renderBenchmark(){
  const b=D.benchmark||{}; const maxRank=Math.max(100,b.rank||100); const angle=Math.max(12,Math.min(360,(1-(Number(b.rank||1)-1)/maxRank)*360));
  $('#benchmarkCard').innerHTML=`<div class="section-head"><div><div class="section-title">比较基准</div><div class="section-sub">市场整体相对位置</div></div><span class="tag">BENCHMARK</span></div><div class="benchmark-top"><div><div class="ticker">${esc(b.display||b.ticker||D.benchmark_label)}</div><div class="name" title="${esc(b.name)}">${esc(b.name||D.benchmark_label)}</div></div><div class="rank-orb" style="--rank-angle:${angle}deg"><span>#${b.rank??'—'}</span></div></div><div class="metric-row"><div class="mini-metric"><div class="mini-label">收盘价</div><div class="mini-value">${price(b.close)}</div></div><div class="mini-metric"><div class="mini-label">ATR 得分</div><div class="mini-value ${cls(b.atr_score)}">${fmt(b.atr_score,3)}</div></div><div class="mini-metric"><div class="mini-label">价格 vs 重心</div><div class="mini-value ${cls(b.price_vs_center_pct)}">${pct(b.price_vs_center_pct)}</div></div><div class="mini-metric"><div class="mini-label">3日涨跌</div><div class="mini-value ${cls(b.price_change_3d_pct)}">${pct(b.price_change_3d_pct)}</div></div></div>`;
}
function renderLeaders(){
  const rows=(D.top20||[]).slice(0,3);
  $('#leaderGrid').innerHTML=rows.length?rows.map(x=>`<article class="leader"><div class="leader-rank">${x.rank}</div><div class="leader-ticker">${esc(x.display||x.ticker)}</div><div class="leader-type">${esc(x.stock_type||'未分类')} · ${esc(x.sector||'—')}</div><div class="leader-score ${cls(x.atr_score)}">${fmt(x.atr_score,3)}</div><div class="leader-footer"><span>ATR 动能</span><span class="${cls(x.daily_change_pct)}">日涨跌 ${pct(x.daily_change_pct)}</span></div><div class="leader-footer" style="margin-top:8px"><span>价格距重心</span><span class="${cls(x.price_vs_center_pct)}">${pct(x.price_vs_center_pct)}</span></div></article>`).join(''):'<div class="empty">暂无强势股票</div>';
}
function renderBars(sel,rows,limit=8){
  const list=(rows||[]).slice(0,limit); const max=Math.max(...list.map(x=>Number(x.pct||0)),1);
  $(sel).innerHTML=list.length?list.map(x=>`<div class="bar-row"><div class="bar-label" title="${esc(x.stock_type||x.name)}">${esc(x.stock_type||x.name)}</div><div class="bar-track"><div class="bar-fill" data-w="${Math.max(3,Number(x.pct||0)/max*100)}"></div></div><div class="bar-value">${fmt(x.pct,1)}%</div></div>`).join(''):'<div class="empty">暂无分类数据</div>';
  requestAnimationFrame(()=>$$(`${sel} .bar-fill`).forEach(el=>el.style.width=el.dataset.w+'%'));
}
function computedIndustry(rows,prefer='sector'){
  const map=new Map();
  (rows||[]).forEach(x=>{const key=(prefer==='stock_type'?x.stock_type:x.sector)||x.stock_type||x.sector||'未分类';map.set(key,(map.get(key)||0)+1)});
  const total=(rows||[]).length||1;
  return [...map.entries()].map(([name,count])=>({name,count,pct:count/total*100})).sort((a,b)=>b.count-a.count||String(a.name).localeCompare(String(b.name)));
}
function industryStats(key,rows){
  const pre=pathGet(D.type_stats||{},key);
  if(Array.isArray(pre)&&pre.length){
    const total=(rows||[]).length||pre.reduce((s,x)=>s+Number(x.count||0),0)||1;
    const list=pre.map(x=>({name:x.stock_type||x.name||'未分类',count:Number(x.count||0),pct:Number(x.count||0)/total*100}));
    const used=list.reduce((s,x)=>s+x.count,0); if(used<total)list.push({name:'其他',count:total-used,pct:(total-used)/total*100});
    return list.sort((a,b)=>b.count-a.count||String(a.name).localeCompare(String(b.name)));
  }
  return computedIndustry(rows,key==='technology_focus.top10'?'stock_type':'sector');
}
function industryHTML(rows,key){
  const stats=industryStats(key,rows); const total=(rows||[]).length; const max=Math.max(...stats.map(x=>x.pct),1);
  if(!total)return '<div class="empty">该榜单暂无股票，无法计算行业占比</div>';
  return `<div class="industry-overview"><div><div class="industry-total">${total} 只</div><div class="industry-caption">${stats.length} 个行业类别</div></div><div class="industry-caption">按榜单股票数量计算</div></div>${stats.map(x=>`<div class="industry-row"><div class="industry-row-top"><div class="industry-name" title="${esc(x.name)}">${esc(x.name)}</div><div class="industry-value">${x.count} 只 · ${fmt(x.pct,1)}%</div></div><div class="industry-track"><div class="industry-fill" style="width:${Math.max(2,x.pct/max*100)}%"></div></div></div>`).join('')}<div class="industry-note">分类口径：优先采用 JSON 中的 type_stats；若该榜单未提供预计算统计，则按 sector 聚合。预计算统计未覆盖的股票会归入“其他”。</div>`;
}

const moverState={up:'detail',down:'detail'};
function moverRows(kind){
  const rows=(kind==='up'?D.upward_moves:D.downward_moves)||[];
  return rows.slice().sort((a,b)=>kind==='up'?Number(b.daily_change_pct||0)-Number(a.daily_change_pct||0):Number(a.daily_change_pct||0)-Number(b.daily_change_pct||0));
}
function renderMover(kind){
  const rows=moverRows(kind); const list=$(`#${kind}List`), panel=$(`#${kind}Industry`), btn=$(`#${kind}ViewToggle`);
  const item=x=>`<div class="mover"><div class="mover-rank">#${x.rank??'—'}</div><div><div class="mover-symbol">${esc(x.display||x.ticker)}</div><div class="mover-meta">${esc(x.stock_type||x.sector||'未分类')}</div></div><div class="mover-change ${cls(x.daily_change_pct)}">${pct(x.daily_change_pct)}<div class="mover-rankchange ${cls(x.rank_change)}">排名 ${signed(x.rank_change)}</div></div></div>`;
  list.innerHTML=rows.length?rows.map(item).join(''):'<div class="empty">暂无数据</div>';
  panel.innerHTML=industryHTML(rows,kind==='up'?'upward_moves':'downward_moves');
  const industry=moverState[kind]==='industry'; list.classList.toggle('hidden',industry); panel.classList.toggle('hidden',!industry); btn.classList.toggle('active',industry); btn.textContent=industry?'返回明细':'行业占比';
  $(`#${kind}Count`).textContent=`${rows.length} 只`;
}
function initMovers(){
  ['up','down'].forEach(kind=>{ $(`#${kind}ViewToggle`).onclick=()=>{moverState[kind]=moverState[kind]==='detail'?'industry':'detail';renderMover(kind)};renderMover(kind)});
}
function renderAI(){
  const m=D.model_interpretation||{}; const text=String(m.text||'').trim();
  const paragraphs=text.split(/\n\s*\n/).map(x=>x.trim()).filter(Boolean);
  $('#aiCopy').innerHTML=paragraphs.length?paragraphs.map(p=>{const lines=p.split(/\n+/).map(x=>x.trim()).filter(Boolean);const h=lines.shift()||'模型观察';return `<div class="ai-block"><div class="ai-heading">${esc(h)}</div><div>${esc(lines.join(' ')||h)}</div></div>`}).join(''):'<div class="empty">暂无模型解读</div>';
  $('#aiMeta').innerHTML=`<span class="chip">状态 <b>${esc(m.status||'—')}</b></span><span class="chip">模型 <b>${esc(m.model||m.provider||'—')}</b></span>`;
}
function renderTech(){
  const section=$('#techSection'),tab=$('#techTableTab');
  if(!hasTech()){section?.classList.add('hidden');tab?.classList.add('hidden');return}
  section?.classList.remove('hidden');tab?.classList.remove('hidden');
  const t=D.technology_focus||{}; $('#techCount').textContent=t.count??'—'; $('#techTop20').textContent=t.top20_count??'—';
  renderBars('#techBars',t.industry_distribution||[],10);
  $('#techWatch').innerHTML=(t.strong_up||[]).length?(t.strong_up||[]).map(x=>`<div class="watch"><div><b>${esc(x.display||x.ticker)}</b><div class="mover-meta">${esc(x.stock_type||x.sector||'未分类')}</div></div><span class="${cls(x.daily_change_pct)}">${pct(x.daily_change_pct)}</span></div>`).join(''):'<div class="empty">暂无显著上涨股票</div>';
}
function renderStable(){
  const rows=D.stable_top20||[];
  $('#stableWatch').innerHTML=rows.length?rows.map(x=>`<div class="watch"><div><b>${esc(x.display||x.ticker)}</b><div class="mover-meta">均位 ${fmt(x.avg_rank_5,1)}</div></div><span>#${x.rank??'—'}</span></div>`).join(''):'<div class="empty">暂无稳定前20股票</div>';
}

const columns=[['rank','排名'],['ticker','代码'],['stock_type','类型'],['name','公司'],['close','收盘'],['atr_score','ATR'],['price_vs_center_pct','距重心'],['price_change_3d_pct','3日涨跌'],['daily_change_pct','日涨跌'],['rank_change','排名变化']];
let tableMode='top20',sortKey='rank',sortDir=1,tableView='detail';
function currentRows(){const rows=pathGet(D,tableMode);return Array.isArray(rows)?rows:[]}
function renderTable(){
  $('#tableHead').innerHTML='<tr>'+columns.map(([k,l])=>`<th data-key="${k}">${l}${sortKey===k?(sortDir===1?' ↑':' ↓'):''}</th>`).join('')+'</tr>';
  const q=$('#tableSearch').value.trim().toLowerCase(); let rows=currentRows().filter(x=>!q||[x.ticker,x.display,x.name,x.stock_type,x.sector].some(v=>String(v||'').toLowerCase().includes(q)));
  rows=rows.slice().sort((a,b)=>{const av=a[sortKey],bv=b[sortKey];if(num(av)!==null&&num(bv)!==null)return(Number(av)-Number(bv))*sortDir;return String(av??'').localeCompare(String(bv??''))*sortDir});
  $('#tableBody').innerHTML=rows.length?rows.map(x=>`<tr><td><span class="rank-badge">${x.rank??'—'}</span></td><td class="symbol-cell">${esc(x.ticker)}</td><td><span class="type-pill">${esc(x.stock_type||x.sector||'未分类')}</span></td><td title="${esc(x.name)}">${esc(x.name||x.display||'—')}</td><td>${price(x.close)}</td><td class="${cls(x.atr_score)}">${fmt(x.atr_score,3)}</td><td class="${cls(x.price_vs_center_pct)}">${pct(x.price_vs_center_pct)}</td><td class="${cls(x.price_change_3d_pct)}">${pct(x.price_change_3d_pct)}</td><td class="${cls(x.daily_change_pct)}">${pct(x.daily_change_pct)}</td><td class="${cls(x.rank_change)} ${Number(x.rank_change)>0?'rank-up':Number(x.rank_change)<0?'rank-down':''}">${signed(x.rank_change)}</td></tr>`).join(''):'<tr><td colspan="10"><div class="empty">没有匹配结果</div></td></tr>';
  $$('#tableHead th').forEach(th=>th.onclick=()=>{const k=th.dataset.key;if(sortKey===k)sortDir*=-1;else{sortKey=k;sortDir=1}renderTable()});
  $('#mainIndustryView').innerHTML=industryHTML(currentRows(),tableMode);
}
function applyMainView(){
  const industry=tableView==='industry'; $('#mainTableWrap').classList.toggle('hidden',industry); $('#mainIndustryView').classList.toggle('hidden',!industry); $('#tableSearch').classList.toggle('hidden',industry); $('#mainViewToggle').classList.toggle('active',industry); $('#mainViewToggle').textContent=industry?'返回明细':'行业占比';
  if(industry)$('#mainIndustryView').innerHTML=industryHTML(currentRows(),tableMode);
}
function initTable(){
  $$('#tableTabs .tab-btn').forEach(btn=>btn.onclick=()=>{$$('#tableTabs .tab-btn').forEach(x=>x.classList.remove('active'));btn.classList.add('active');tableMode=btn.dataset.mode;sortKey='rank';sortDir=1;renderTable();applyMainView()});
  $('#tableSearch').addEventListener('input',renderTable); $('#mainViewToggle').onclick=()=>{tableView=tableView==='detail'?'industry':'detail';applyMainView()}; renderTable();applyMainView();
}
function initRankChart(){
  const keys=Object.keys(D.rank_history||{}),sel=$('#rankTicker'); if(!keys.length){sel.classList.add('hidden');$('#rankChart').innerHTML='<div class="empty">暂无排名轨迹</div>';return}
  const benchmarkKey=D.benchmark?.ticker; sel.innerHTML=keys.map(k=>`<option value="${esc(k)}" ${k===benchmarkKey?'selected':''}>${esc(k)}</option>`).join(''); sel.onchange=()=>renderRankChart(sel.value);renderRankChart(keys.includes(benchmarkKey)?benchmarkKey:keys[0]);
}
function renderRankChart(ticker){
  const rows=D.rank_history?.[ticker]||[];if(!rows.length){$('#rankChart').innerHTML='<div class="empty">暂无轨迹</div>';return}
  const ranks=rows.map(x=>Number(x.rank)),W=760,H=260,P={l:40,r:18,t:18,b:40},min=Math.max(1,Math.min(...ranks)-5),max=Math.max(...ranks)+5;
  const x=i=>P.l+i*(W-P.l-P.r)/Math.max(1,rows.length-1),y=v=>P.t+(v-min)*(H-P.t-P.b)/Math.max(1,max-min),pts=rows.map((r,i)=>[x(i),y(r.rank)]),d=pts.map((p,i)=>(i?'L':'M')+p.join(',')).join(' '),ticks=[min,min+(max-min)/2,max];
  const grid=ticks.map(v=>`<line class="chart-grid" x1="${P.l}" x2="${W-P.r}" y1="${y(v)}" y2="${y(v)}"/><text class="chart-axis" x="${P.l-8}" y="${y(v)+3}" text-anchor="end">${Math.round(v)}</text>`).join(''),labels=rows.map((r,i)=>i%2===0||i===rows.length-1?`<text class="chart-axis" x="${x(i)}" y="${H-15}" text-anchor="middle">${String(r.date).slice(5)}</text>`:'').join(''),dots=rows.map((r,i)=>`<circle class="chart-dot" cx="${x(i)}" cy="${y(r.rank)}" r="4"><title>${r.date} · 排名 #${r.rank}</title></circle>`).join('');
  $('#rankChart').innerHTML=`<svg class="chart-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><defs><linearGradient id="lineGradient"><stop offset="0" stop-color="var(--accent)"/><stop offset="1" stop-color="var(--accent2)"/></linearGradient></defs>${grid}<path class="chart-line" d="${d}"/>${dots}${labels}</svg>`;
  const delta=ranks[0]-ranks[ranks.length-1];$('#chartSummary').innerHTML=`<b>${esc(ticker)}</b>：${rows[0].date} 的 #${ranks[0]} → ${rows.at(-1).date} 的 #${ranks.at(-1)}，<span class="${cls(delta)}">${delta>0?'改善':delta<0?'回落':'持平'} ${Math.abs(delta)} 位</span>`;
}
function initActions(){$('#themeBtn').onclick=()=>{const html=document.documentElement;html.dataset.theme=html.dataset.theme==='dark'?'light':'dark'};$('#printBtn').onclick=()=>window.print()}

renderMeta();renderKPIs();renderSummary();renderBenchmark();renderLeaders();renderBars('#typeBars',D.type_stats?.top20?.length?D.type_stats.top20:computedIndustry(D.top20||[],'sector').map(x=>({stock_type:x.name,count:x.count,pct:x.pct})),8);initMovers();renderAI();renderTech();renderStable();initTable();initRankChart();initActions();
</script>
</body></html>"""


def load_report(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError as exc:
        raise SystemExit(f"找不到 JSON 文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON 格式错误：{exc}") from exc

    if not isinstance(data, dict):
        raise SystemExit("JSON 根节点必须是对象。")
    if not isinstance(data.get("top20", []), list):
        raise SystemExit("字段 top20 必须是数组。")
    return data


def generate_html(data: dict[str, Any], theme: str = "dark") -> str:
    # Prevent a JSON string from accidentally closing the script element.
    report_json = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")

    html = TEMPLATE.replace("__REPORT_JSON__", report_json, 1)
    html = html.replace('data-theme="dark"', f'data-theme="{theme}"', 1)
    return html


def default_output(input_path: Path) -> Path:
    date = ""
    try:
        with input_path.open("r", encoding="utf-8") as file:
            date = str(json.load(file).get("as_of_date", ""))
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    suffix = f"_{date}" if date else ""
    return input_path.with_name(f"{input_path.stem}{suffix}_report.html")


def main() -> None:
    parser = argparse.ArgumentParser(description="根据量化日报 JSON 生成单文件 HTML。")
    parser.add_argument("input", type=Path, help="日报 JSON 路径")
    parser.add_argument("-o", "--output", type=Path, help="输出 HTML 路径")
    parser.add_argument("--theme", choices=("dark", "light"), default="dark", help="默认主题")
    args = parser.parse_args()

    data = load_report(args.input)
    output = args.output or default_output(args.input)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(generate_html(data, args.theme), encoding="utf-8")
    print(f"已生成：{output.resolve()}")


if __name__ == "__main__":
    main()
