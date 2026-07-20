from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from add_stock_to_pool import normalize_ticker, upsert_pool_entry  # noqa: E402


def test_normalize_ticker_for_cn_and_hk() -> None:
    assert normalize_ticker("002432.SZ", "cn") == "002432"
    assert normalize_ticker("0020.HK", "hk") == "00020"


def test_upsert_cn_stock_keeps_one_row_and_defaults_related_us(tmp_path: Path) -> None:
    path = tmp_path / "cn_stock_pool.csv"
    first, action = upsert_pool_entry(
        path, "cn", "002432.SZ", "九安医疗", "医疗健康", "医疗器械/IVD"
    )
    assert action == "added"
    assert first.to_dict("records") == [
        {
            "ticker": "002432",
            "name": "九安医疗",
            "sector": "医疗健康",
            "stock_type": "医疗器械/IVD",
            "related_us": "-",
        }
    ]
    first.to_csv(path, index=False, encoding="utf-8-sig")

    second, action = upsert_pool_entry(
        path, "cn", "002432", "九安医疗", "医疗健康", "体外诊断/家用检测"
    )
    assert action == "updated"
    assert len(second) == 1
    assert second.iloc[0]["stock_type"] == "体外诊断/家用检测"
    assert second.iloc[0]["related_us"] == "-"


def test_upsert_hk_stock_normalizes_code_and_keeps_optional_fields(tmp_path: Path) -> None:
    path = tmp_path / "hk_stock_pool.csv"
    df, action = upsert_pool_entry(
        path,
        "hk",
        "0020.HK",
        "商汤 - W",
        "人工智能",
        "视觉AI平台",
        is_hstech="Y",
        source_url="https://example.com/source",
    )
    assert action == "added"
    assert df.iloc[0].to_dict() == {
        "ticker": "00020",
        "name": "商汤 - W",
        "sector": "人工智能",
        "stock_type": "视觉AI平台",
        "is_hstech": "Y",
        "source": "https://example.com/source",
    }
