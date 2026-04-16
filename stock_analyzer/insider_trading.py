#!/usr/bin/env python3
"""
내부자 거래 분석 모듈 (Insider Trading Analysis)
- SEC Form 4 데이터 수집
- 내부자 매수/매도 패턴 분석
- 거래 규모 및 빈도 평가
- 신호 강도 계산
"""

import os
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import yfinance as yf


class InsiderTradingAnalyzer:
    """내부자 거래 분석기"""

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

    def fetch_insider_data(self, ticker: str, days: int = 90) -> pd.DataFrame:
        """
        내부자 거래 데이터 수집

        Args:
            ticker: 종목 심볼
            days: 조회 기간 (일)

        Returns:
            내부자 거래 데이터프레임
        """
        try:
            # yfinance를 통한 내부자 거래 데이터 수집
            stock = yf.Ticker(ticker)
            insider_trades = stock.insider_trades

            if insider_trades is None or insider_trades.empty:
                # 대체 데이터 소스 시도 (finviz API 스타일)
                return self._fetch_from_alternative_source(ticker, days)

            # 날짜 필터링
            cutoff_date = pd.Timestamp.now() - pd.Timedelta(days=days)
            insider_trades = insider_trades[insider_trades.index >= cutoff_date]

            return insider_trades

        except Exception as e:
            print(f"내부자 거래 데이터 수집 오류: {str(e)}")
            return pd.DataFrame()

    def _fetch_from_alternative_source(self, ticker: str, days: int) -> pd.DataFrame:
        """대체 소스에서 내부자 거래 데이터 수집 (모의 구현)"""
        # 실제 구현시 SEC EDGAR API 또는 다른 금융 API 사용
        # 여기서는 구조만 제시

        try:
            # SEC EDGAR API 호출 (실제 구현 필요)
            # url = f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={ticker}&type=4"

            # 모의 데이터 생성 (실제 구현시 제거)
            return pd.DataFrame({
                'Date': [],
                'Insider': [],
                'Position': [],
                'Transaction': [],
                'Shares': [],
                'Value': [],
                'Price': []
            })

        except Exception as e:
            return pd.DataFrame()

    def analyze_insider_pattern(self, df: pd.DataFrame, current_price: float) -> Dict[str, Any]:
        """
        내부자 거래 패턴 분석

        Args:
            df: 내부자 거래 데이터프레임
            current_price: 현재 주가

        Returns:
            분석 결과 딕셔너리
        """
        if df.empty:
            return self._empty_result()

        # 거래 유형별 집계
        buy_trades = df[df['Shares'] > 0] if 'Shares' in df.columns else pd.DataFrame()
        sell_trades = df[df['Shares'] < 0] if 'Shares' in df.columns else pd.DataFrame()

        # 최근 30일 집중 분석
        recent_cutoff = pd.Timestamp.now() - pd.Timedelta(days=30)
        recent_buys = buy_trades[buy_trades.index >= recent_cutoff] if not buy_trades.empty else pd.DataFrame()
        recent_sells = sell_trades[sell_trades.index >= recent_cutoff] if not sell_trades.empty else pd.DataFrame()

        # 거래 규모 계산
        total_buy_value = buy_trades['Value'].sum() if not buy_trades.empty and 'Value' in buy_trades else 0
        total_sell_value = abs(sell_trades['Value'].sum()) if not sell_trades.empty and 'Value' in sell_trades else 0

        recent_buy_value = recent_buys['Value'].sum() if not recent_buys.empty and 'Value' in recent_buys else 0
        recent_sell_value = abs(recent_sells['Value'].sum()) if not recent_sells.empty and 'Value' in recent_sells else 0

        # C-Suite 거래 확인
        c_suite_keywords = ['CEO', 'CFO', 'COO', 'President', 'Chairman', 'Director']
        c_suite_trades = pd.DataFrame()

        if 'Position' in df.columns:
            c_suite_mask = df['Position'].str.contains('|'.join(c_suite_keywords), case=False, na=False)
            c_suite_trades = df[c_suite_mask]

        # 신호 강도 계산
        signal_score = self._calculate_signal_score(
            buy_trades, sell_trades,
            recent_buys, recent_sells,
            c_suite_trades, current_price
        )

        # 신호 결정
        if signal_score > 3:
            signal = "buy"
        elif signal_score < -3:
            signal = "sell"
        else:
            signal = "neutral"

        return {
            "tool": "insider_trading",
            "name": "내부자 거래 분석",
            "signal": signal,
            "score": signal_score,
            "buy_count": len(buy_trades),
            "sell_count": len(sell_trades),
            "recent_buy_count": len(recent_buys),
            "recent_sell_count": len(recent_sells),
            "total_buy_value": total_buy_value,
            "total_sell_value": total_sell_value,
            "recent_buy_value": recent_buy_value,
            "recent_sell_value": recent_sell_value,
            "c_suite_trades": len(c_suite_trades),
            "net_insider_position": total_buy_value - total_sell_value,
            "recent_net_position": recent_buy_value - recent_sell_value,
            "detail": self._generate_detail(
                signal, signal_score,
                recent_buys, recent_sells,
                c_suite_trades
            )
        }

    def _calculate_signal_score(self, buy_trades, sell_trades,
                                recent_buys, recent_sells,
                                c_suite_trades, current_price) -> float:
        """내부자 거래 신호 점수 계산"""
        score = 0.0

        # 1. 최근 거래 방향성 (±4점)
        if len(recent_sells) > len(recent_buys) * 2:
            score -= 4  # 최근 매도 압도적
        elif len(recent_sells) > len(recent_buys):
            score -= 2  # 최근 매도 우세
        elif len(recent_buys) > len(recent_sells) * 2:
            score += 4  # 최근 매수 압도적
        elif len(recent_buys) > len(recent_sells):
            score += 2  # 최근 매수 우세

        # 2. C-Suite 거래 (±3점)
        if not c_suite_trades.empty:
            c_suite_recent = c_suite_trades[c_suite_trades.index >= (pd.Timestamp.now() - pd.Timedelta(days=30))]
            if not c_suite_recent.empty:
                if 'Shares' in c_suite_recent.columns:
                    c_suite_net = c_suite_recent['Shares'].sum()
                    if c_suite_net < 0:
                        score -= 3  # C-Suite 순매도
                    elif c_suite_net > 0:
                        score += 3  # C-Suite 순매수

        # 3. 거래 규모 (±2점)
        if 'Value' in buy_trades.columns and 'Value' in sell_trades.columns:
            recent_net_value = (
                (recent_buys['Value'].sum() if not recent_buys.empty else 0) -
                abs(recent_sells['Value'].sum() if not recent_sells.empty else 0)
            )

            if recent_net_value < -10000000:  # 1000만 달러 이상 순매도
                score -= 2
            elif recent_net_value > 10000000:  # 1000만 달러 이상 순매수
                score += 2

        # 4. 거래 집중도 (±1점)
        # 2주 내 5건 이상 동일 방향 거래시 신호 강화
        very_recent = pd.Timestamp.now() - pd.Timedelta(days=14)
        very_recent_buys = buy_trades[buy_trades.index >= very_recent] if not buy_trades.empty else pd.DataFrame()
        very_recent_sells = sell_trades[sell_trades.index >= very_recent] if not sell_trades.empty else pd.DataFrame()

        if len(very_recent_sells) >= 5:
            score -= 1
        elif len(very_recent_buys) >= 5:
            score += 1

        return round(score, 1)

    def _generate_detail(self, signal: str, score: float,
                        recent_buys, recent_sells,
                        c_suite_trades) -> str:
        """상세 설명 생성"""
        details = []

        if signal == "sell":
            details.append(f"내부자 매도 신호 (점수: {score})")
        elif signal == "buy":
            details.append(f"내부자 매수 신호 (점수: {score})")
        else:
            details.append(f"내부자 중립 (점수: {score})")

        details.append(f"최근 30일: 매수 {len(recent_buys)}건, 매도 {len(recent_sells)}건")

        if not c_suite_trades.empty:
            details.append(f"경영진 거래 {len(c_suite_trades)}건 감지")

        return " / ".join(details)

    def _empty_result(self) -> Dict[str, Any]:
        """데이터 없을 때 기본 결과"""
        return {
            "tool": "insider_trading",
            "name": "내부자 거래 분석",
            "signal": "neutral",
            "score": 0,
            "buy_count": 0,
            "sell_count": 0,
            "recent_buy_count": 0,
            "recent_sell_count": 0,
            "total_buy_value": 0,
            "total_sell_value": 0,
            "recent_buy_value": 0,
            "recent_sell_value": 0,
            "c_suite_trades": 0,
            "net_insider_position": 0,
            "recent_net_position": 0,
            "detail": "내부자 거래 데이터 없음"
        }

    def analyze(self, ticker: str, current_price: float = None) -> Dict[str, Any]:
        """
        내부자 거래 종합 분석

        Args:
            ticker: 종목 심볼
            current_price: 현재 주가 (선택)

        Returns:
            분석 결과
        """
        # 현재 주가 확인
        if current_price is None:
            try:
                stock = yf.Ticker(ticker)
                current_price = stock.info.get('currentPrice', 0)
            except:
                current_price = 0

        # 데이터 수집
        insider_df = self.fetch_insider_data(ticker)

        # 패턴 분석
        result = self.analyze_insider_pattern(insider_df, current_price)

        return result


# 독립 실행 테스트
if __name__ == "__main__":
    analyzer = InsiderTradingAnalyzer()

    # BAC 테스트
    result = analyzer.analyze("BAC")

    print(json.dumps(result, indent=2, ensure_ascii=False))