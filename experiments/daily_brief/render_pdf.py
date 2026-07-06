from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT_DIR = Path(__file__).resolve().parents[2]
EXPERIMENT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = EXPERIMENT_DIR / "output"
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

from generate_brief_data import build_brief, build_rule_based_analysis  # noqa: E402


PAGE_SIZE = landscape(A4)
PAGE_W, PAGE_H = PAGE_SIZE
MARGIN = 30
FONT = "BriefCJK"
FONT_BOLD = "BriefCJK"
INK = colors.HexColor("#172033")
MUTED = colors.HexColor("#637083")
GRID = colors.HexColor("#d9e2ee")
BLUE = colors.HexColor("#1f6feb")
GREEN = colors.HexColor("#08764f")
RED = colors.HexColor("#b42318")
PANEL = colors.HexColor("#f8fafc")
HEADER = colors.HexColor("#edf3fb")
BAR_BG = colors.HexColor("#edf1f6")
AMBER = colors.HexColor("#a16207")


def register_font() -> None:
    global FONT, FONT_BOLD
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simsun.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        Path("/usr/share/fonts/truetype/arphic/ukai.ttc"),
        Path("/usr/share/fonts/truetype/arphic/uming.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for path in candidates:
        if path.exists():
            try:
                pdfmetrics.registerFont(TTFont(FONT, str(path)))
                return
            except Exception as exc:
                print(f"Skip unsupported CJK font {path}: {exc}")
    FONT = "STSong-Light"
    FONT_BOLD = "STSong-Light"
    pdfmetrics.registerFont(UnicodeCIDFont(FONT))


def text(c: canvas.Canvas, value: Any, x: float, y: float, size: float = 9, color=INK, bold: bool = False) -> None:
    c.setFillColor(color)
    c.setFont(FONT_BOLD if bold else FONT, size)
    c.drawString(x, y, str(value))


def right_text(c: canvas.Canvas, value: Any, x: float, y: float, size: float = 9, color=INK, bold: bool = False) -> None:
    c.setFillColor(color)
    c.setFont(FONT_BOLD if bold else FONT, size)
    c.drawRightString(x, y, str(value))


def center_text(c: canvas.Canvas, value: Any, x: float, y: float, size: float = 9, color=INK, bold: bool = False) -> None:
    c.setFillColor(color)
    c.setFont(FONT_BOLD if bold else FONT, size)
    c.drawCentredString(x, y, str(value))


def panel(c: canvas.Canvas, x: float, y: float, w: float, h: float, fill=colors.white, stroke=GRID) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.roundRect(x, y, w, h, 8, fill=1, stroke=1)


def wrapped(
    c: canvas.Canvas,
    value: str,
    x: float,
    y: float,
    width: float,
    size: float = 8,
    leading: float = 11,
    color=MUTED,
    max_lines: int | None = None,
) -> float:
    c.setFillColor(color)
    c.setFont(FONT, size)
    lines: list[str] = []
    for paragraph in str(value).replace("\r\n", "\n").split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            candidate = current + char
            if pdfmetrics.stringWidth(candidate, FONT, size) <= width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = char
        if current:
            lines.append(current)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip("。；，、 ") + "..."
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def fmt(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "--"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "--"
    return f"{number:.{digits}f}{suffix}"


def pct_color(value: Any):
    try:
        return GREEN if float(value) >= 0 else RED
    except (TypeError, ValueError):
        return MUTED


def delta_label(item: dict[str, Any]) -> tuple[str, Any]:
    change = item.get("rank_change")
    if change is None:
        return "--", MUTED
    if change > 0:
        return f"+{change}", GREEN
    if change < 0:
        return f"{change}", RED
    return "0", MUTED


def draw_header(c: canvas.Canvas, brief: dict[str, Any], page_label: str) -> None:
    text(c, f"{brief.get('market_label', '美股')} Ranking Monitor", MARGIN, PAGE_H - 28, 8, MUTED, True)
    right_text(c, page_label, PAGE_W - MARGIN, PAGE_H - 28, 8, MUTED)
    c.setStrokeColor(GRID)
    c.line(MARGIN, PAGE_H - 40, PAGE_W - MARGIN, PAGE_H - 40)
    text(c, f"窗口 {brief['window']} 日 / 截止 {brief['as_of_date']}", MARGIN, PAGE_H - 54, 8, MUTED)


def metric_card(c: canvas.Canvas, x: float, y: float, w: float, h: float, label: str, value: str, tone=INK, note: str = "") -> None:
    panel(c, x, y, w, h, colors.white, GRID)
    text(c, label, x + 10, y + h - 18, 8, MUTED, True)
    text(c, value, x + 10, y + 15, 17, tone, True)
    if note:
        right_text(c, note, x + w - 10, y + 17, 7.5, MUTED)


def draw_model_block(c: canvas.Canvas, brief: dict[str, Any], x: float, y: float, w: float, h: float) -> None:
    panel(c, x, y, w, h, colors.white, GRID)
    info = brief.get("model_interpretation") or {}
    source = "模型生成" if info.get("status") == "ok" else "规则兜底"
    text(c, "模型行情解读", x + 16, y + h - 26, 15, INK, True)
    right_text(c, source, x + w - 16, y + h - 24, 8, MUTED)
    body = str(info.get("text") or "").strip() or build_rule_based_analysis(brief)
    wrapped(c, body, x + 16, y + h - 52, w - 32, 9.0, 14, INK, max_lines=int((h - 62) // 14))


def draw_distribution(c: canvas.Canvas, title: str, rows: list[dict[str, Any]], x: float, y: float, w: float, h: float, accent=BLUE) -> None:
    panel(c, x, y, w, h, colors.white, GRID)
    text(c, title, x + 12, y + h - 22, 12, INK, True)
    if not rows:
        text(c, "暂无数据", x + 12, y + h / 2, 9, MUTED)
        return
    cursor = y + h - 48
    max_count = max(int(row.get("count") or 0) for row in rows) or 1
    for index, row in enumerate(rows[:8], start=1):
        label = str(row.get("stock_type", "--"))[:12]
        count = int(row.get("count") or 0)
        pct = float(row.get("pct") or 0)
        text(c, f"{index}. {label}", x + 12, cursor + 1, 8.2, INK, True)
        right_text(c, f"{count} / {pct:.1f}%", x + w - 12, cursor + 1, 8, MUTED)
        bar_x = x + 104
        bar_w = w - 188
        c.setFillColor(BAR_BG)
        c.roundRect(bar_x, cursor - 2, bar_w, 7, 3.5, fill=1, stroke=0)
        c.setFillColor(accent)
        c.roundRect(bar_x, cursor - 2, max(3, bar_w * count / max_count), 7, 3.5, fill=1, stroke=0)
        cursor -= 20
        if cursor < y + 14:
            break


def draw_item_table(
    c: canvas.Canvas,
    title: str,
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str, float]],
    x: float,
    y: float,
    w: float,
    h: float,
    max_rows: int = 14,
) -> None:
    panel(c, x, y, w, h, colors.white, GRID)
    text(c, title, x + 12, y + h - 22, 12, INK, True)
    header_y = y + h - 42
    c.setFillColor(HEADER)
    c.roundRect(x + 8, header_y - 5, w - 16, 18, 4, fill=1, stroke=0)
    for label, _key, col_x in columns:
        text(c, label, x + col_x, header_y, 7.2, MUTED, True)
    row_y = header_y - 19
    for row in rows[:max_rows]:
        for _label, key, col_x in columns:
            value: Any
            color = INK
            bold = False
            if key == "ticker":
                value, color, bold = str(row.get("display") or row.get("ticker") or "--")[:10], BLUE, True
            elif key == "rank_change":
                value, color = delta_label(row)
                bold = True
            elif key == "daily_change_pct":
                value = fmt(row.get(key), 2, "%")
                color, bold = pct_color(row.get(key)), True
            elif key == "atr_score":
                value = fmt(row.get(key), 2)
                color = GREEN if (row.get(key) or 0) >= 0 else RED
                bold = True
            elif key == "price_vs_center_pct":
                value = fmt(row.get(key), 1, "%")
                color = pct_color(row.get(key))
            elif key == "stock_type":
                value = str(row.get(key, "--"))[:8]
            elif key == "close":
                value = fmt(row.get(key), 2)
            else:
                value = row.get(key, "--")
            text(c, value, x + col_x, row_y, 7.4, color, bold)
        row_y -= 16
        if row_y < y + 13:
            break
    if not rows:
        text(c, "暂无", x + 16, y + h / 2, 9, MUTED)
    elif len(rows) > max_rows:
        right_text(c, f"+{len(rows) - max_rows} more", x + w - 12, y + 9, 7, MUTED)


def render_page_one(c: canvas.Canvas, brief: dict[str, Any]) -> None:
    draw_header(c, brief, "Overview / 01")
    text(c, "每日排名异常监测简报", MARGIN, PAGE_H - 86, 23, INK, True)
    text(c, f"生成时间 {brief['generated_at']}", MARGIN, PAGE_H - 105, 8.5, MUTED)

    benchmark = brief.get("benchmark", {})
    benchmark_label = brief.get("benchmark_label", "QQQ")
    card_y = PAGE_H - 174
    card_w = 148
    metric_card(c, MARGIN, card_y, card_w, 54, f"{benchmark_label} 排名", f"#{benchmark.get('rank', '--')}", BLUE)
    metric_card(c, MARGIN + 164, card_y, card_w, 54, f"{benchmark_label} ATR倍数", fmt(benchmark.get("atr_score"), 3), GREEN if (benchmark.get("atr_score") or 0) >= 0 else RED)
    metric_card(c, MARGIN + 328, card_y, card_w, 54, f"{benchmark_label} 较重心", fmt(benchmark.get("price_vs_center_pct"), 2, "%"), pct_color(benchmark.get("price_vs_center_pct")))
    metric_card(c, MARGIN + 492, card_y, card_w, 54, "收盘日", brief.get("as_of_date", "--"), INK)

    draw_model_block(c, brief, MARGIN, 48, PAGE_W - MARGIN * 2, PAGE_H - 250)
    c.showPage()


def render_page_two(c: canvas.Canvas, brief: dict[str, Any]) -> None:
    draw_header(c, brief, "Type Ranking / 02")
    text(c, "异常股类型占比排名", MARGIN, PAGE_H - 86, 22, INK, True)
    text(c, "用类型占比观察强势股集中在哪里，以及异常变化是否来自少数方向。", MARGIN, PAGE_H - 104, 8.5, MUTED)
    gap = 14
    box_w = (PAGE_W - MARGIN * 2 - gap) / 2
    box_h = 188
    top_y = PAGE_H - 322
    bottom_y = 62
    stats = brief.get("type_stats", {})
    draw_distribution(c, "稳定前20 类型占比", stats.get("stable_top20", []), MARGIN, top_y, box_w, box_h, BLUE)
    draw_distribution(c, "大幅上升 类型占比", stats.get("upward_moves", []), MARGIN + box_w + gap, top_y, box_w, box_h, GREEN)
    draw_distribution(c, "大幅下降 类型占比", stats.get("downward_moves", []), MARGIN, bottom_y, box_w, box_h, RED)
    draw_distribution(c, "今日Top20 类型占比", stats.get("top20", []), MARGIN + box_w + gap, bottom_y, box_w, box_h, AMBER)
    c.showPage()


def render_page_three(c: canvas.Canvas, brief: dict[str, Any]) -> None:
    draw_header(c, brief, "Technology / 03")
    text(c, "科技股专项分析", MARGIN, PAGE_H - 86, 22, INK, True)
    text(c, "单独拆出半导体、软件、互联网、云计算、硬件、光通信等科技方向，观察内部轮动。", MARGIN, PAGE_H - 104, 8.5, MUTED)
    tech = brief.get("technology_focus", {})
    metric_card(c, MARGIN, PAGE_H - 168, 130, 48, "科技池数量", f"{tech.get('count', 0)} 只", BLUE)
    metric_card(c, MARGIN + 146, PAGE_H - 168, 130, 48, "科技前20数量", f"{tech.get('top20_count', 0)} 只", GREEN)
    first_type = (tech.get("industry_distribution") or [{}])[0]
    metric_card(c, MARGIN + 292, PAGE_H - 168, 180, 48, "科技主导类型", str(first_type.get("stock_type", "--")), INK, f"{first_type.get('count', 0)}只")

    left_w = 438
    right_w = PAGE_W - MARGIN * 2 - left_w - 14
    columns = [
        ("#", "rank", 14),
        ("代码", "ticker", 48),
        ("类型", "stock_type", 104),
        ("日涨跌", "daily_change_pct", 184),
        ("ATR", "atr_score", 252),
        ("较重心", "price_vs_center_pct", 314),
    ]
    draw_item_table(c, "科技类型股票排名前十", tech.get("top10", []), columns, MARGIN, 58, left_w, 352, max_rows=10)
    draw_distribution(c, "科技内部类型占比", tech.get("industry_distribution", []), MARGIN + left_w + 14, 236, right_w, 174, BLUE)
    up_columns = [
        ("代码", "ticker", 14),
        ("类型", "stock_type", 72),
        ("日涨跌", "daily_change_pct", 150),
        ("排名变动", "rank_change", 216),
        ("ATR", "atr_score", 286),
    ]
    draw_item_table(c, "科技股显著上涨", tech.get("strong_up", []), up_columns, MARGIN + left_w + 14, 58, right_w, 164, max_rows=7)
    c.showPage()


def render_page_four(c: canvas.Canvas, brief: dict[str, Any]) -> None:
    draw_header(c, brief, "Alerts / 05")
    text(c, "异常股票明细", MARGIN, PAGE_H - 86, 22, INK, True)
    text(c, "大幅上升和大幅下降按当日涨跌幅降序展示，同时保留排名变动和 ATR 倍数。", MARGIN, PAGE_H - 104, 8.5, MUTED)
    gap = 12
    box_w = (PAGE_W - MARGIN * 2 - gap * 2) / 3
    box_h = 338
    box_y = 62
    cols = [
        ("#", "rank", 12),
        ("代码", "ticker", 42),
        ("类型", "stock_type", 82),
        ("日涨跌", "daily_change_pct", 142),
        ("ATR", "atr_score", 190),
        ("变动", "rank_change", 226),
    ]
    draw_item_table(c, "最近5日稳定前20", brief.get("stable_top20", []), cols, MARGIN, box_y, box_w, box_h, max_rows=16)
    draw_item_table(c, "大幅上升", brief.get("upward_moves", []), cols, MARGIN + box_w + gap, box_y, box_w, box_h, max_rows=16)
    draw_item_table(c, "大幅下降", brief.get("downward_moves", []), cols, MARGIN + (box_w + gap) * 2, box_y, box_w, box_h, max_rows=16)
    c.showPage()


def render_page_five(c: canvas.Canvas, brief: dict[str, Any]) -> None:
    draw_header(c, brief, "Top20 / 04")
    text(c, "今日 Top20 排名表", MARGIN, PAGE_H - 86, 22, INK, True)
    columns = [
        ("#", "rank", 16),
        ("代码", "ticker", 54),
        ("股票类型", "stock_type", 118),
        ("收盘", "close", 214),
        ("日涨跌", "daily_change_pct", 284),
        ("ATR倍数", "atr_score", 360),
        ("较重心", "price_vs_center_pct", 440),
        ("排名变动", "rank_change", 520),
    ]
    draw_item_table(c, "按 ATR 倍数排序", brief.get("top20", []), columns, MARGIN, 58, PAGE_W - MARGIN * 2, PAGE_H - 170, max_rows=20)
    c.showPage()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render daily ranking brief PDF.")
    parser.add_argument("--window", type=int, default=10, choices=[10], help="Ranking window. Daily brief uses 10-day window only.")
    parser.add_argument("--market", choices=["us", "cn", "hk"], default="us", help="Market to render when --input is not provided.")
    parser.add_argument("--as-of-date", default=None, help="Use cached date on or before YYYY-MM-DD.")
    parser.add_argument("--input", default=None, help="Existing brief JSON path.")
    parser.add_argument("--output", default=None, help="Output PDF path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    register_font()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.input:
        input_path = Path(args.input)
        brief = json.loads(input_path.read_text(encoding="utf-8"))
    else:
        brief = build_brief(args.window, args.as_of_date, top_n=20, move_threshold=10, market=args.market)
        json_path = OUTPUT_DIR / f"daily_brief_{brief['market']}_{brief['as_of_date']}_w{brief['window']}.json"
        json_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")

    output = Path(args.output) if args.output else OUTPUT_DIR / f"daily_brief_{brief.get('market', 'us')}_{brief['as_of_date']}_w{brief['window']}.pdf"
    c = canvas.Canvas(str(output), pagesize=PAGE_SIZE)
    c.setTitle(f"Daily Ranking Brief {brief['as_of_date']} W{brief['window']}")
    render_page_one(c, brief)
    render_page_two(c, brief)
    if brief.get("market", "us") == "us":
        render_page_three(c, brief)
    render_page_five(c, brief)
    render_page_four(c, brief)
    c.save()
    print(f"PDF written: {output}")


if __name__ == "__main__":
    main()
