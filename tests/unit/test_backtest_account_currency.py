"""백테스트 계좌 규모 통화 정합 테스트 (2026-07 진단).

ACCOUNT_SIZE(USD 스케일 100k)를 KRW 종목에 그대로 쓰면 리스크 예산이
~1,000원이 되어 호가 수만원대 종목은 수량 int(1000/stop)=0 → 전 전략
무거래 (워치리스트 KR 고가 4종목 실측). KR 종목은 ACCOUNT_SIZE_KRW 사용.
"""

import os
import sys

import numpy as np
import pandas as pd

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from backtest_engine import _account_size_for, backtest_sma_cross  # noqa: E402
from config import ACCOUNT_SIZE, ACCOUNT_SIZE_KRW  # noqa: E402


def test_account_size_selected_by_market():
    assert _account_size_for("057050.KS") == ACCOUNT_SIZE_KRW
    assert _account_size_for("950170.KQ") == ACCOUNT_SIZE_KRW
    assert _account_size_for("MSFT") == ACCOUNT_SIZE
    assert ACCOUNT_SIZE_KRW >= 10_000_000, "KRW 계좌가 너무 작으면 고가 종목 수량 0 재발"


def _krw_highprice_df_with_cross(rows=280, base=60_000.0):
    """SMA20/50 골든크로스와 데드크로스가 모두 발생하는 고가 종목 시뮬레이션.

    엔진은 청산 완료된 거래만 total_trades로 집계하므로 (미청산 포지션은
    equity에만 반영) 진입 후 청산까지 재현되는 왕복 패턴이 필요하다.
    """
    q = rows // 4
    down1 = np.linspace(base * 1.3, base, q)
    up = np.linspace(base, base * 1.5, q)
    down2 = np.linspace(base * 1.5, base * 0.9, q)
    flat = np.linspace(base * 0.9, base * 0.95, rows - 3 * q)
    closes = np.concatenate([down1, up, down2, flat])
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.01,
            "Low": closes * 0.99,
            "Close": closes,
            "Volume": np.full(rows, 100_000.0),
        },
        index=pd.date_range("2025-01-01", periods=rows, freq="B"),
    )
    df["ATR"] = (df["High"] - df["Low"]).rolling(14).mean()
    return df


def test_krw_highprice_ticker_actually_trades():
    """골든크로스가 있는 고가 KRW 종목에서 거래가 발생해야 한다 (회귀: 항상 0)."""
    df = _krw_highprice_df_with_cross()
    result = backtest_sma_cross("057050.KS", df).to_dict()

    assert result["total_trades"] >= 1, "KRW 계좌 스케일 적용 후에도 무거래 — 회귀"


def test_us_ticker_unaffected():
    """미국 종목은 기존 ACCOUNT_SIZE 경로 그대로 거래가 발생한다."""
    df = _krw_highprice_df_with_cross(base=300.0)  # USD 스케일 가격
    result = backtest_sma_cross("MSFT", df).to_dict()

    assert result["total_trades"] >= 1
