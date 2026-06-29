from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
COMPANY_PROFILES_FILE = ROOT_DIR / "data" / "fundamental" / "company_profiles.csv"


SUMMARY_FIXES = {
    "BRK.B": "伯克希尔哈撒韦是一家多元化控股公司，旗下业务覆盖保险、铁路、能源、公用事业、制造、服务和零售等多个领域。保险业务是公司的核心板块，主要包括 Geico、Berkshire Hathaway Reinsurance Group 和 Berkshire Hathaway Primary Group。公司长期利用经营业务产生的现金流进行并购和投资，持有 Burlington Northern Santa Fe 铁路、Berkshire Hathaway Energy 以及 Precision Castparts、Lubrizol、Clayton Homes、Marmon 等实体业务。伯克希尔的特点是高度去中心化管理，各子公司保持较强经营自主权，同时集团层面强调长期资本配置能力。",
    "CBRS": "Cerebras Systems 是一家专注于人工智能基础设施的半导体公司，主要面向大模型训练和推理场景。公司设计超大规模 AI 芯片，并围绕芯片构建供电、散热、数据输入输出和系统软件，形成完整的 AI 超算系统。其软件栈支持 PyTorch 等常见机器学习框架，目标是让复杂 AI 工作负载更容易部署和扩展。客户可以用 Cerebras 系统训练大模型，也可以通过本地部署或云端方式使用其推理能力。公司业务与 AI 算力、先进封装、数据中心基础设施和高性能计算需求密切相关。",
    "DELL": "戴尔科技是一家综合信息技术硬件和解决方案供应商，主要服务企业客户。公司业务覆盖商用和高端个人电脑、企业级服务器、本地数据中心硬件、外部存储和显示设备等领域。戴尔在个人电脑、主流服务器、外围显示器和外部存储市场拥有较高份额，是全球重要的企业 IT 基础设施供应商。公司依赖广泛的零部件、组装和渠道合作伙伴完成产品交付与销售。随着 AI 服务器和企业数据中心投资增加，戴尔的服务器、存储和基础设施解决方案也成为市场关注重点。",
    "GLW": "康宁是一家材料科技公司，主要提供玻璃、陶瓷和光纤相关产品，业务覆盖显示、光通信、汽车、生命科学、移动消费电子和太阳能等多个终端市场。公司收入较大的板块包括电视和显示器用显示玻璃，以及服务电信网络和数据中心的光纤产品。康宁还为智能手机提供保护玻璃，为汽车提供过滤器、基板和玻璃材料，并生产药用玻璃和太阳能多晶硅相关产品。公司在多类材料和制造工艺上具有纵向整合能力，和光通信、消费电子、汽车电子等产业链关系较深。",
    "JNJ": "强生是全球规模最大、业务最广泛的医疗健康公司之一。剥离消费者健康业务 Kenvue 后，公司目前主要由创新药和医疗科技两大板块构成。创新药业务聚焦免疫、肿瘤和神经科学等治疗领域，医疗科技业务覆盖手术、骨科、介入和视觉健康等方向。强生在全球医疗体系中拥有较强品牌、渠道和研发资源，美国市场贡献了公司超过一半的收入。公司业务兼具大型药企的研发管线属性和医疗器械企业的稳定需求特征。",
    "JPM": "摩根大通是全球领先的综合金融服务集团，业务覆盖消费者银行、商业银行、投资银行、资产管理和财富管理等领域。公司在美国拥有庞大的零售银行网点和客户基础，同时在全球投资银行业务中长期保持领先地位。其资产负债表规模、存款基础和客户资产管理规模均处于行业前列。摩根大通收入来源多元，既受利率、信贷周期和资本市场活跃度影响，也受财富管理和支付清算等长期金融服务需求支撑，是观察美国金融体系和资本市场景气度的重要标的。",
    "LLY": "礼来是一家全球大型制药公司，研发重点集中在神经科学、心血管代谢、肿瘤和免疫等领域。公司核心产品包括用于糖尿病和减重相关治疗的 Mounjaro、Zepbound、Trulicity、Humalog 和 Humulin，以及肿瘤药 Verzenio、Jaypirca，免疫领域药物 Taltz 和 Olumiant 等。近年来，礼来因 GLP-1 类药物在糖尿病和减重市场的快速放量而受到市场高度关注。公司具备较强研发能力和商业化能力，业绩表现与创新药管线、适应症扩展和全球药品定价环境密切相关。",
    "MRK": "默沙东是一家全球制药公司，产品覆盖肿瘤、心血管代谢、感染性疾病、疫苗和动物保健等领域。公司最重要的增长来源之一是以 Keytruda 为核心的肿瘤免疫治疗平台，该产品在多种癌症适应症中具有重要地位。默沙东还拥有疫苗业务，包括预防儿童疾病的疫苗以及人乳头瘤病毒疫苗 Gardasil。此外，公司经营动物保健相关药品。美国人用健康业务，包括药品和疫苗，是公司收入的重要来源。默沙东的投资关注点主要包括 Keytruda 生命周期、后续管线和专利到期后的增长接续。",
    "V": "Visa 是全球最大的支付网络和交易处理公司之一，连接消费者、商户、金融机构和政府客户。公司并不主要承担信用风险，而是通过授权、清算和结算网络处理电子支付交易，并从支付规模和交易笔数中获得收入。Visa 网络覆盖 200 多个国家和地区，支持 160 多种货币，系统每秒可处理数万笔交易。公司受益于全球现金支付向电子支付迁移、跨境消费恢复和数字商务增长。其业务具有高利润率、强网络效应和较轻资本开支特征。",
    "XOM": "埃克森美孚是一家全球一体化油气公司，业务覆盖油气勘探、生产、炼化、运输和化工。公司在全球范围内生产原油、天然气和液体能源产品，并拥有庞大的油气储量。埃克森美孚也是全球重要炼油商之一，具备大规模炼化产能，同时生产大宗化工和特种化工产品。公司业绩受国际油价、天然气价格、炼化价差、化工需求和资本开支周期影响较大。作为能源巨头，埃克森美孚兼具上游资源属性和下游炼化化工一体化优势。",
}


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return [{key: str(value or "").strip() for key, value in row.items()} for row in reader]


def save_rows(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rows = load_rows(COMPANY_PROFILES_FILE)
    updated_at = datetime.now().isoformat(timespec="seconds")
    updated = 0
    for row in rows:
        ticker = row.get("ticker", "").upper()
        if ticker in SUMMARY_FIXES:
            row["summary_zh"] = SUMMARY_FIXES[ticker]
            row["updated_at"] = updated_at
            updated += 1
    save_rows(COMPANY_PROFILES_FILE, rows, list(rows[0].keys()))
    print(f"Updated summaries: {updated}")
    print(f"Output: {COMPANY_PROFILES_FILE}")


if __name__ == "__main__":
    main()
