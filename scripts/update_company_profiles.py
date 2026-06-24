from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
OUTPUT_FILE = ROOT_DIR / "data" / "fundamental" / "company_profiles.csv"
POLYGON_TICKER_DETAILS_URL = "https://api.polygon.io/v3/reference/tickers/{ticker}"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from app.services.ranking_service import RankingConfig, build_ranking  # noqa: E402
from download_polygon_daily import ApiKeyPool, load_api_keys  # noqa: E402


FIELDNAMES = [
    "ticker",
    "name",
    "market",
    "exchange",
    "locale",
    "primary_exchange",
    "currency_name",
    "market_cap",
    "sic_description",
    "homepage_url",
    "description",
    "summary_zh",
    "source",
    "updated_at",
]

KNOWN_SUMMARIES_ZH = {
    "ADI": "Analog Devices 是领先的模拟、混合信号和数字信号处理芯片厂商。公司在转换器芯片领域拥有显著市场份额，这类芯片用于在模拟信号和数字信号之间进行转换。ADI 服务数万家客户，超过一半的芯片销售来自工业和汽车终端市场，其芯片也被用于无线基础设施设备。",
    "ALAB": "Astera Labs 设计并提供面向云计算和 AI 基础设施的半导体连接解决方案。公司的智能连接平台整合半导体技术、微控制器、传感器和软件，以提升性能、可扩展性和数据管理能力。其产品包括集成电路、板卡和模块，主要面向超大规模云厂商和系统 OEM，应用集中在 AI 平台的数据、网络和内存管理。",
    "AMAT": "Applied Materials 是全球最大的半导体晶圆制造设备厂商。公司产品覆盖晶圆制造设备生态的大部分环节，并在沉积设备领域占据领先份额，沉积工艺用于在半导体晶圆上形成新材料层。公司业务更偏向由 IDM 和晶圆代工厂制造的通用逻辑芯片，主要客户包括台积电、英特尔和三星等全球大型芯片制造商。",
    "ASML": "ASML 是半导体制造光刻系统龙头，市场份额约 90%。光刻是使用光源将光罩上的电路图案曝光到半导体晶圆上的过程，是先进芯片制造中的关键步骤，也长期占据高端芯片制造成本的重要部分。ASML 多数零部件制造外包，自身更像系统组装商，主要客户包括台积电、三星、英特尔、SK 海力士和美光。",
    "DASH": "DoorDash 成立于 2013 年，是在线配送需求聚合平台。消费者可以通过应用向合作商户点餐，并选择配送或到店取货。收购 Wolt 后，公司也在欧洲和亚洲提供服务。DoorDash 为商户建立线上市场、推广商品并通过配送满足需求，同时也把类似服务扩展到杂货、零售、宠物用品等非餐饮场景，并尝试无人机配送等新技术。",
    "FER": "Ferrovial 是全球交通基础设施投资、开发和运营商，在北美收费公路领域布局较深。近几年公司将资产组合重心转向北美和印度，并降低欧洲敞口，包括出售希思罗机场股份。核心资产包括多伦多 407 ETR 收费公路 99 年运营租约权益，以及纽约 JFK 新一号航站楼开发和运营特许权。",
    "INTC": "Intel 是领先的数字芯片制造商，专注于为全球个人电脑和数据中心市场设计并制造微处理器。公司开创了 x86 微处理器架构，并曾引领半导体制造沿摩尔定律演进。Intel 仍是 PC 和服务器 CPU 市场份额领导者，同时正在重振 Intel Foundry 芯片制造业务，并发展 Intel Products 产品业务。",
    "KLAC": "KLA 是全球大型半导体晶圆制造设备厂商之一，专注于半导体过程控制设备。其设备在研发和制造过程中检查晶圆缺陷，并验证关键尺寸和精密测量。KLA 在该细分市场拥有多数份额，同时也少量涉足刻蚀和沉积设备。主要客户包括台积电、三星等全球大型芯片制造商。",
    "LRCX": "Lam Research 是全球大型半导体晶圆制造设备厂商之一，专长在沉积和刻蚀环节。沉积用于在半导体上形成材料层，刻蚀则选择性移除各层中的图案。Lam 在刻蚀设备市场份额领先，在沉积设备中位居明确第二。公司对 DRAM 和 NAND 等存储芯片厂商敞口较高，主要客户包括台积电、三星、英特尔和美光。",
    "MCHP": "Microchip Technology 于 1989 年从 General Instrument 分拆独立。公司超过一半收入来自 MCU 微控制器，这类芯片广泛用于遥控器、车库门开关、汽车电动车窗等电子设备。公司优势在适用于更广泛、技术复杂度较低设备的低端 8 位 MCU，同时也扩展到更高端 MCU 和模拟芯片。",
    "MNST": "Monster Beverage 是非酒精即饮饮料市场中能量饮料品类的领导者，约三分之二收入来自美国和加拿大。知名 Monster 品牌包括 Monster Energy、Monster Ultra、Java Monster 和 Juice Monster。公司还拥有 Reign、NOS、Burn、Bang、Mother 等能量饮料品牌，并在 2022 年收购精酿啤酒商后进入啤酒和调味麦芽饮料领域。",
    "MU": "Micron 是全球最大的半导体公司之一，专注于内存和存储芯片。公司主要收入来自 DRAM 动态随机存取存储器，同时也有 NAND 闪存芯片敞口。Micron 面向全球客户销售芯片，应用覆盖数据中心、手机、消费电子、工业和汽车等领域，并采用垂直整合模式。",
    "NBIS": "Nebius 是一家垂直整合的云服务提供商，聚焦 AI 和高性能计算。公司由原俄罗斯科技公司 Yandex 分拆而来，背景与俄乌战争后的制裁和业务重组有关。Nebius 在欧洲和美国设计并运营自有数据中心和服务器，总容量达到数百兆瓦。2025 年 9 月，微软成为其重要客户，双方签署多年期、约 170 亿美元算力容量协议。",
    "SNDK": "Sandisk 是全球五大 NAND 闪存半导体供应商之一。公司采用垂直整合模式，通过与 Kioxia 的合资框架，在日本制造基地生产几乎全部闪存芯片。随后 Sandisk 将多数芯片重新封装成面向消费电子、外部存储和云存储的 SSD。Sandisk 曾在 2016 年被 Western Digital 收购，并在 2025 年分拆为独立公司。",
    "STX": "Seagate Technology 是面向企业和消费市场的数据存储硬盘驱动器主要供应商。公司与主要竞争对手 Western Digital 在硬盘市场形成事实上的双寡头格局，两家公司都采用垂直整合模式。",
    "TER": "Teradyne 提供测试设备，包括半导体自动测试设备、硬盘系统测试、电路板和电子系统测试，以及无线设备测试。公司在 2015 年进入工业自动化市场，销售用于工厂应用的协作机器人和自主机器人。Teradyne 服务多个终端市场和地区，但最重要的敞口仍是半导体测试，客户包括 IDM、无晶圆厂和晶圆代工芯片制造商。",
    "TTWO": "Take-Two 是全球大型游戏开发商和发行商之一，旗下品牌包括 Rockstar、2K 和 Zynga。Grand Theft Auto 是公司最大 IP，过去十年约贡献总销售额的 30%。NBA 2K 是行业领先的篮球游戏，每年推出新版本。其他重要系列包括 Red Dead Redemption、Borderlands 和 Civilization。公司多数销售来自游戏内消费，收购 Zynga 后移动端约占总销售一半。",
    "TXN": "总部位于达拉斯的 Texas Instruments 超过 95% 收入来自半导体，其余来自知名计算器业务。公司是全球最大的模拟芯片制造商，模拟芯片用于处理声音、电源等现实世界信号。Texas Instruments 在处理器和微控制器领域也拥有领先市场份额，产品广泛应用于各类电子设备。",
    "VRTX": "Vertex Pharmaceuticals 是全球生物科技公司，发现并开发用于治疗严重疾病的小分子药物。其核心药物包括用于囊性纤维化的 Kalydeco、Orkambi、Symdeko、Trikafta/Kaftrio 和 Alyftrek，Vertex 疗法仍是全球标准治疗方案。公司还通过 Casgevy 基因编辑疗法、Journavx 非阿片止痛药等拓展组合，并研究 APOL1 肾病抑制剂和 1 型糖尿病细胞疗法。",
    "WDC": "Western Digital 是领先的垂直整合硬盘驱动器供应商。硬盘市场实际上由 Western Digital 和 Seagate 两大厂商构成双寡头格局。Western Digital 设计并制造 HDD，制造和员工布局很大一部分位于亚洲。HDD 的主要消费方是数据中心。",
}


def compact_text(value: object, max_length: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:max_length].rstrip() if max_length and len(text) > max_length else text


def market_cap_text(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "暂无市值数据"
    if number >= 1_000_000_000_000:
        return f"约 {number / 1_000_000_000_000:.2f} 万亿美元"
    if number >= 1_000_000_000:
        return f"约 {number / 1_000_000_000:.1f} 十亿美元"
    if number >= 1_000_000:
        return f"约 {number / 1_000_000:.1f} 百万美元"
    return f"约 {number:,.0f} 美元"


def build_summary(profile: dict[str, Any]) -> str:
    ticker = compact_text(profile.get("ticker")).upper()
    if ticker in KNOWN_SUMMARIES_ZH:
        return KNOWN_SUMMARIES_ZH[ticker]

    description = compact_text(profile.get("description"))
    if description:
        return description

    name = compact_text(profile.get("name")) or ticker
    exchange = compact_text(profile.get("primary_exchange") or profile.get("exchange")) or "美股市场"
    sic = compact_text(profile.get("sic_description")) or "未披露行业"
    market_cap = market_cap_text(profile.get("market_cap"))
    return f"{ticker}（{name}）是一家在 {exchange} 交易的上市公司，Polygon 将其行业归类为 {sic}，当前市值{market_cap}。当前 Polygon 未提供详细业务描述。"


def refresh_cached_summaries(path: Path = OUTPUT_FILE) -> int:
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"Company profile cache not found: {path}")
    rows: list[dict[str, str]] = []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            normalized = {field: compact_text(row.get(field)) for field in FIELDNAMES}
            normalized["summary_zh"] = build_summary(normalized)
            rows.append(normalized)
    save_rows(rows, path)
    return len(rows)


def looks_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def translate_text_google(text: str) -> str:
    text = compact_text(text)
    if not text:
        return ""
    response = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={
            "client": "gtx",
            "sl": "en",
            "tl": "zh-CN",
            "dt": "t",
            "q": text,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return "".join(part[0] for part in payload[0] if part and part[0]).strip()


def translate_cached_descriptions(path: Path = OUTPUT_FILE, sleep_seconds: float = 0.2) -> int:
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"Company profile cache not found: {path}")
    rows: list[dict[str, str]] = []
    updated = 0
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            normalized = {field: compact_text(row.get(field)) for field in FIELDNAMES}
            ticker = normalized["ticker"].upper()
            if ticker in KNOWN_SUMMARIES_ZH:
                normalized["summary_zh"] = KNOWN_SUMMARIES_ZH[ticker]
            elif normalized["description"]:
                translated = translate_text_google(normalized["description"])
                if translated:
                    normalized["summary_zh"] = translated
            elif not looks_chinese(normalized["summary_zh"]):
                normalized["summary_zh"] = build_summary(normalized)
            if looks_chinese(normalized["summary_zh"]):
                updated += 1
            rows.append(normalized)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    save_rows(rows, path)
    return updated


def ranked_tickers(limit: int | None, window: int) -> list[str]:
    ranking = build_ranking(RankingConfig(window=window, benchmark="QQQ", apply_announced_rebalance=True))
    rows = ranking["data"] if limit is None else ranking["data"][:limit]
    return [str(row["ticker"]) for row in rows]


def request_ticker_details(ticker: str, api_key: str) -> dict[str, Any]:
    response = requests.get(
        POLYGON_TICKER_DETAILS_URL.format(ticker=ticker),
        params={"apiKey": api_key},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get("results") or {}


def profile_row(ticker: str, details: dict[str, Any], updated_at: str) -> dict[str, str]:
    row = {
        "ticker": ticker,
        "name": compact_text(details.get("name")),
        "market": compact_text(details.get("market")),
        "exchange": compact_text(details.get("ticker_root") or details.get("market")),
        "locale": compact_text(details.get("locale")),
        "primary_exchange": compact_text(details.get("primary_exchange")),
        "currency_name": compact_text(details.get("currency_name")),
        "market_cap": compact_text(details.get("market_cap")),
        "sic_description": compact_text(details.get("sic_description")),
        "homepage_url": compact_text(details.get("homepage_url")),
        "description": compact_text(details.get("description")),
        "source": "Polygon",
        "updated_at": updated_at,
    }
    row["summary_zh"] = build_summary(row)
    return row


def save_rows(rows: list[dict[str, str]], path: Path = OUTPUT_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    merged: dict[str, dict[str, str]] = {}
    if path.exists() and path.stat().st_size > 0:
        with path.open("r", newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                ticker = compact_text(row.get("ticker")).upper()
                if ticker:
                    merged[ticker] = {field: compact_text(row.get(field)) for field in FIELDNAMES}
    for row in rows:
        ticker = compact_text(row.get("ticker")).upper()
        if ticker:
            merged[ticker] = {field: compact_text(row.get(field)) for field in FIELDNAMES}

    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(merged[ticker] for ticker in sorted(merged))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update local company profile cache from Polygon ticker details.")
    parser.add_argument("--top", type=int, default=20, help="Fetch profiles for top N ranked stocks.")
    parser.add_argument("--all-ranking", action="store_true", help="Fetch profiles for all current ranking rows.")
    parser.add_argument("--window", type=int, default=10, help="Ranking window used to select tickers.")
    parser.add_argument("--tickers", default=None, help="Optional comma-separated ticker override.")
    parser.add_argument("--key-cooldown-seconds", type=int, default=13, help="Cooldown per Polygon API key.")
    parser.add_argument("--sleep-seconds", type=float, default=0, help="Extra sleep after each ticker.")
    parser.add_argument("--translate-cache-only", action="store_true", help="Refresh summary_zh from the existing cache without API calls.")
    parser.add_argument("--machine-translate-cache", action="store_true", help="Translate cached Polygon descriptions to Chinese without fetching Polygon.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.translate_cache_only:
        updated = refresh_cached_summaries()
        print(f"Updated cached summaries: {updated}")
        print(f"Output: {OUTPUT_FILE}")
        return
    if args.machine_translate_cache:
        updated = translate_cached_descriptions(sleep_seconds=max(args.sleep_seconds, 0.0))
        print(f"Chinese cached summaries: {updated}")
        print(f"Output: {OUTPUT_FILE}")
        return

    load_dotenv(ROOT_DIR / ".env")
    api_key_pool = ApiKeyPool(load_api_keys(), cooldown_seconds=args.key_cooldown_seconds)
    if args.tickers:
        tickers = [ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()]
    else:
        tickers = ranked_tickers(None if args.all_ranking else args.top, args.window)

    rows: list[dict[str, str]] = []
    failed: list[str] = []
    updated_at = datetime.now().isoformat(timespec="seconds")
    for ticker in tickers:
        key_number, api_key = api_key_pool.acquire()
        try:
            details = request_ticker_details(ticker, api_key)
            if not details:
                failed.append(ticker)
                continue
            rows.append(profile_row(ticker, details, updated_at))
        except Exception as exc:
            failed.append(f"{ticker}: {exc}")
        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    save_rows(rows)
    print(f"Tickers: {len(tickers)}")
    print(f"Saved profiles: {len(rows)}")
    print(f"Failed: {len(failed)}")
    if failed:
        print("Failed tickers:")
        for item in failed:
            print(f"  {item}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
