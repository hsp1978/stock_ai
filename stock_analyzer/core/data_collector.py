"""
데이터 수집 모듈
- yfinance: 시세, 재무제표, 옵션 데이터
- FRED API: 거시경제 지표
- 데이터 품질 검증 포함
"""
import yfinance as yf
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
from typing import Optional
from config.settings import FRED_API_KEY, DEFAULT_HISTORY_PERIOD


class DataCollector:
    """주식 및 거시경제 데이터 수집기"""

    def __init__(self, ticker: str):
        self.ticker = ticker.upper()
        self.yf_ticker = yf.Ticker(self.ticker)
        self._ohlcv: Optional[pd.DataFrame] = None
        self._info: Optional[dict] = None

    # ── 시세 데이터 ──────────────────────────────────────────

    def get_ohlcv(self, period: str = DEFAULT_HISTORY_PERIOD) -> pd.DataFrame:
        """OHLCV 데이터 수집 + 품질 검증"""
        df = self.yf_ticker.history(period=period, auto_adjust=True)
        if df.empty:
            raise ValueError(f"[{self.ticker}] OHLCV 데이터 수집 실패. 티커 확인 필요.")

        df = self._validate_ohlcv(df)
        self._ohlcv = df
        return df

    def _validate_ohlcv(self, df: pd.DataFrame) -> pd.DataFrame:
        """데이터 품질 검증 및 정제"""
        # 결측치 처리 (Forward Fill -> Backward Fill)
        null_count = df.isnull().sum().sum()
        if null_count > 0:
            print(f"  [경고] {null_count}개 결측치 발견. Forward Fill 적용.")
            df = df.ffill().bfill()

        # 이상치 탐지 (일일 변동률 ±50% 초과 시 경고)
        daily_return = df['Close'].pct_change()
        outliers = daily_return[daily_return.abs() > 0.5]
        if len(outliers) > 0:
            print(f"  [경고] {len(outliers)}개 이상치 탐지 (일일 변동 >50%):")
            for date, val in outliers.items():
                print(f"    {date.strftime('%Y-%m-%d')}: {val:+.1%}")

        # 시간 연속성 체크 (주말/공휴일 제외 후 5일 이상 갭 경고)
        date_diff = pd.Series(df.index).diff().dt.days
        gaps = date_diff[date_diff > 5]
        if len(gaps) > 0:
            print(f"  [정보] {len(gaps)}개 거래일 갭 탐지 (5일 초과). 공휴일 가능성.")

        # Volume 0인 날 제거
        zero_vol = df[df['Volume'] == 0]
        if len(zero_vol) > 0:
            print(f"  [경고] 거래량 0인 날 {len(zero_vol)}개 발견. 제거.")
            df = df[df['Volume'] > 0]

        return df

    # ── 재무 데이터 ──────────────────────────────────────────

    def get_fundamentals(self) -> dict:
        """기업 펀더멘털 데이터 수집"""
        info = self.yf_ticker.info
        self._info = info

        fundamentals = {
            "company_name": info.get("longName", self.ticker),
            "sector": info.get("sector", "N/A"),
            "industry": info.get("industry", "N/A"),
            "market_cap": info.get("marketCap", None),
            # 수익성
            "revenue": info.get("totalRevenue", None),
            "net_income": info.get("netIncomeToCommon", None),
            "profit_margin": info.get("profitMargins", None),
            "operating_margin": info.get("operatingMargins", None),
            "roe": info.get("returnOnEquity", None),
            "roa": info.get("returnOnAssets", None),
            # 가치 평가
            "pe_trailing": info.get("trailingPE", None),
            "pe_forward": info.get("forwardPE", None),
            "ps_ratio": info.get("priceToSalesTrailing12Months", None),
            "pb_ratio": info.get("priceToBook", None),
            "ev_ebitda": info.get("enterpriseToEbitda", None),
            "peg_ratio": info.get("pegRatio", None),
            # 재무 건전성
            "debt_to_equity": info.get("debtToEquity", None),
            "current_ratio": info.get("currentRatio", None),
            "quick_ratio": info.get("quickRatio", None),
            "total_cash": info.get("totalCash", None),
            "total_debt": info.get("totalDebt", None),
            "free_cashflow": info.get("freeCashflow", None),
            # 배당
            "dividend_yield": info.get("dividendYield", None),
            "payout_ratio": info.get("payoutRatio", None),
            # 성장
            "revenue_growth": info.get("revenueGrowth", None),
            "earnings_growth": info.get("earningsGrowth", None),
            # 기타
            "beta": info.get("beta", None),
            "52w_high": info.get("fiftyTwoWeekHigh", None),
            "52w_low": info.get("fiftyTwoWeekLow", None),
            "avg_volume": info.get("averageVolume", None),
            "short_ratio": info.get("shortRatio", None),
            "short_pct_float": info.get("shortPercentOfFloat", None),
        }
        return fundamentals

    # ── 옵션 데이터 (보고서에 없던 부분 - 보완) ────────────

    def get_options_summary(self) -> Optional[dict]:
        """옵션 시장 데이터 요약 (Put/Call Ratio, IV 등)"""
        try:
            expirations = self.yf_ticker.options
            if not expirations:
                return None

            # 가장 가까운 만기 옵션 체인
            nearest_exp = expirations[0]
            chain = self.yf_ticker.option_chain(nearest_exp)

            calls = chain.calls
            puts = chain.puts

            total_call_vol = calls['volume'].sum() if 'volume' in calls else 0
            total_put_vol = puts['volume'].sum() if 'volume' in puts else 0
            total_call_oi = calls['openInterest'].sum() if 'openInterest' in calls else 0
            total_put_oi = puts['openInterest'].sum() if 'openInterest' in puts else 0

            pc_ratio_vol = (total_put_vol / total_call_vol) if total_call_vol > 0 else None
            pc_ratio_oi = (total_put_oi / total_call_oi) if total_call_oi > 0 else None

            # ATM 옵션 IV 추출
            current_price = self._ohlcv['Close'].iloc[-1] if self._ohlcv is not None else None
            atm_iv = None
            if current_price is not None and 'impliedVolatility' in calls.columns:
                calls_sorted = calls.iloc[(calls['strike'] - current_price).abs().argsort()]
                if len(calls_sorted) > 0:
                    atm_iv = calls_sorted.iloc[0].get('impliedVolatility', None)

            return {
                "nearest_expiration": nearest_exp,
                "put_call_ratio_volume": pc_ratio_vol,
                "put_call_ratio_oi": pc_ratio_oi,
                "total_call_volume": int(total_call_vol) if not pd.isna(total_call_vol) else 0,
                "total_put_volume": int(total_put_vol) if not pd.isna(total_put_vol) else 0,
                "atm_implied_volatility": atm_iv,
            }
        except Exception as e:
            print(f"  [경고] 옵션 데이터 수집 실패: {e}")
            return None

    # ── 거시경제 데이터 (FRED API) ───────────────────────────

    @staticmethod
    def get_macro_data() -> dict:
        """FRED API를 통한 거시경제 지표 수집"""
        indicators = {
            "fed_funds_rate": "FEDFUNDS",       # 연방기금금리
            "treasury_10y": "DGS10",            # 10년 국채 수익률
            "treasury_2y": "DGS2",              # 2년 국채 수익률
            "cpi_yoy": "CPIAUCSL",              # 소비자물가지수
            "unemployment": "UNRATE",           # 실업률
            "vix": "VIXCLS",                    # VIX 공포지수
            # ── 추가 거시경제 지표 ──
            "gdp_growth": "A191RL1Q225SBEA",    # 실질 GDP 성장률 (분기)
            "ism_pmi": "MANEMP",                # ISM 제조업 고용지수 (PMI 프록시)
            "consumer_sentiment": "UMCSENT",    # 미시간 소비자심리지수
            "initial_claims": "ICSA",           # 신규 실업수당 청구건수 (주간)
            "m2_money": "M2SL",                 # M2 통화량
        }

        macro = {}
        if not FRED_API_KEY:
            print("  [정보] FRED API 키 없음. 거시경제 데이터 건너뜀.")
            return macro

        for name, series_id in indicators.items():
            try:
                url = (
                    f"https://api.stlouisfed.org/fred/series/observations"
                    f"?series_id={series_id}&api_key={FRED_API_KEY}"
                    f"&file_type=json&sort_order=desc&limit=1"
                )
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                obs = data.get("observations", [])
                if obs and obs[0]["value"] != ".":
                    macro[name] = {
                        "value": float(obs[0]["value"]),
                        "date": obs[0]["date"],
                    }
            except Exception as e:
                print(f"  [경고] FRED {name} 수집 실패: {e}")

        # 10Y-2Y 스프레드 계산 (장단기 금리차 → 경기침체 예측)
        if "treasury_10y" in macro and "treasury_2y" in macro:
            spread = macro["treasury_10y"]["value"] - macro["treasury_2y"]["value"]
            macro["yield_spread_10y_2y"] = {
                "value": round(spread, 3),
                "date": macro["treasury_10y"]["date"],
                "interpretation": "역전(음수) 시 경기침체 가능성 상승"
            }

        return macro

    # ── 내부자 거래 데이터 (보고서에 없던 부분 - 보완) ──────

    # ── 섹터 상대강도 ────────────────────────────────────────

    def get_sector_relative_strength(self, period: str = "6mo") -> Optional[dict]:
        """종목의 SPY/섹터 ETF 대비 상대 수익률"""
        # 주요 섹터 → ETF 매핑
        SECTOR_ETF_MAP = {
            "Technology": "XLK",
            "Healthcare": "XLV",
            "Financial Services": "XLF",
            "Financials": "XLF",
            "Consumer Cyclical": "XLY",
            "Consumer Defensive": "XLP",
            "Communication Services": "XLC",
            "Industrials": "XLI",
            "Energy": "XLE",
            "Utilities": "XLU",
            "Real Estate": "XLRE",
            "Basic Materials": "XLB",
        }

        try:
            info = self._info or self.yf_ticker.info
            sector = info.get("sector", "")
            sector_etf = SECTOR_ETF_MAP.get(sector)

            # SPY 데이터
            spy = yf.Ticker("SPY").history(period=period, auto_adjust=True)
            stock = self._ohlcv if self._ohlcv is not None else self.yf_ticker.history(period=period, auto_adjust=True)

            if spy.empty or stock.empty:
                return None

            # 기간별 상대 수익률 계산
            def _relative_returns(stock_s: pd.Series, bench_s: pd.Series):
                """여러 기간의 상대수익률"""
                result = {}
                for days, label in [(5, "1w"), (21, "1m"), (63, "3m"), (126, "6m")]:
                    if len(stock_s) > days and len(bench_s) > days:
                        stock_ret = float(stock_s.iloc[-1] / stock_s.iloc[-days] - 1) * 100
                        bench_ret = float(bench_s.iloc[-1] / bench_s.iloc[-days] - 1) * 100
                        result[label] = {
                            "stock": round(stock_ret, 2),
                            "benchmark": round(bench_ret, 2),
                            "relative": round(stock_ret - bench_ret, 2),
                        }
                return result

            spy_close = spy['Close']
            stock_close = stock['Close']

            rs_vs_spy = _relative_returns(stock_close, spy_close)

            result = {
                "sector": sector,
                "vs_spy": rs_vs_spy,
            }

            # 섹터 ETF 비교
            if sector_etf:
                try:
                    sector_df = yf.Ticker(sector_etf).history(period=period, auto_adjust=True)
                    if not sector_df.empty:
                        sector_close = sector_df['Close']
                        rs_vs_sector = _relative_returns(stock_close, sector_close)
                        result["sector_etf"] = sector_etf
                        result["vs_sector"] = rs_vs_sector
                except Exception:
                    pass

            # 상대강도 점수 산출 (SPY 대비 6m 초과수익률 기준)
            if "6m" in rs_vs_spy:
                rel = rs_vs_spy["6m"]["relative"]
                if rel > 15:
                    result["rs_rating"] = "very_strong"
                elif rel > 5:
                    result["rs_rating"] = "strong"
                elif rel > -5:
                    result["rs_rating"] = "neutral"
                elif rel > -15:
                    result["rs_rating"] = "weak"
                else:
                    result["rs_rating"] = "very_weak"

            return result

        except Exception as e:
            print(f"  [경고] 섹터 상대강도 수집 실패: {e}")
            return None

    # ── 내부자 거래 데이터 (보고서에 없던 부분 - 보완) ──────

    def get_insider_trades(self) -> list:
        """최근 내부자 거래 요약"""
        try:
            insiders = self.yf_ticker.insider_transactions
            if insiders is None or insiders.empty:
                return []

            recent = insiders.head(10)
            trades = []
            for _, row in recent.iterrows():
                trades.append({
                    "insider": row.get("Insider", "Unknown"),
                    "relation": row.get("Insider Relation", "Unknown"),
                    "transaction": row.get("Transaction", "Unknown"),
                    "shares": row.get("Shares", 0),
                    "date": str(row.get("Start Date", "")),
                })
            return trades
        except Exception:
            return []
