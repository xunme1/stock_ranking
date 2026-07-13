from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from ths_ifind_daily import ths_code_candidates  # noqa: E402


def test_csi_500_uses_shanghai_index_code() -> None:
    assert ths_code_candidates("000905", "cn") == ["000905.SH"]


def test_explicit_cn_suffix_is_preserved() -> None:
    assert ths_code_candidates("000905.SZ", "cn") == ["000905.SZ"]
