"""시장 지수·환율 데이터.

`webui.py` 분해 3단계 (CLAUDE.md §6-10). 화면 렌더가 아니라 **데이터 정의와 수집**만
담는다 — 차트·티커바 컴포넌트는 아직 webui 에 있다.

원화 환율은 yfinance 직접 페어를 쓸 수 없어 USD 페어에서 교차 계산한다 (아래 KRW_CROSS
주석 참조).
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st
import yfinance as yf

MARKET_INDICES = {
    "us_market": {
        "title": "US",
        "items": [
            ("^GSPC", "S&P 500", 2),
            ("^IXIC", "NASDAQ", 2),
            ("^DJI", "DOW", 2),
        ],
    },
    "kr_market": {
        "title": "KR",
        "items": [
            ("^KS11", "KOSPI", 2),
            ("^KQ11", "KOSDAQ", 2),
        ],
    },
    # 환율 — 수출 비중이 큰 국내 종목 판단에 원화뿐 아니라 엔/위안 흐름도 참고된다.
    # 표기는 모두 'USD 기준 1달러당' (JPY=X, CNY=X는 yfinance에서 USD/JPY, USD/CNY).
    "fx": {
        "title": "FX",
        "items": [
            ("KRW:USD", "원/달러", 2),
            ("KRW:JPY", "원/100엔", 2),
            ("KRW:CNY", "원/위안", 2),
        ],
    },
    "commodities": {
        "title": "CMDTY",
        "items": [
            ("GC=F", "Gold", 2),
            ("SI=F", "Silver", 2),
            ("HG=F", "Copper", 3),
            ("NG=F", "Nat Gas", 2),
        ],
    },
}


# 원화 기준 환율 — 국내 사용자 관점에서 "1달러가 몇 원인가"로 읽는다.
# yfinance의 원화 직접 페어는 쓸 수 없다: JPYKRW=X는 봉이 성기고
# CNYKRW=X는 1봉뿐이라 등락률·차트를 만들 수 없다 (2026-08-06 실측).
# USD 페어에서 교차 계산한다 — 직접 티커와 값이 일치함을 확인했다
# (원/위안 교차 210.61 vs 직접 210.66).
# 엔은 국내 관례대로 100엔 기준으로 표기한다.
KRW_CROSS = {
    "KRW:USD": {"num": "USDKRW=X", "den": None, "mult": 1},
    "KRW:JPY": {"num": "USDKRW=X", "den": "JPY=X", "mult": 100},
    "KRW:CNY": {"num": "USDKRW=X", "den": "CNY=X", "mult": 1},
}


def _krw_cross_series(close_of, symbol: str):
    """교차 환율 시계열. close_of(base_symbol) → Series 를 받아 계산한다."""
    spec = KRW_CROSS[symbol]
    num = close_of(spec["num"])
    if num is None or len(num) == 0:
        return None
    if spec["den"] is None:
        series = num
    else:
        den = close_of(spec["den"])
        if den is None or len(den) == 0:
            return None
        joined = pd.concat([num, den], axis=1, join="inner").dropna()
        if joined.empty:
            return None
        series = joined.iloc[:, 0] / joined.iloc[:, 1]
    return (series * spec["mult"]).dropna()


@st.cache_data(ttl=300)
def fetch_market_indices() -> tuple[dict, str]:
    results = {}
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 교차 환율은 원 심볼 대신 계산에 필요한 base 티커를 받아온다.
    all_tickers = []
    for group in MARKET_INDICES.values():
        for sym, name, decimals in group["items"]:
            if sym in KRW_CROSS:
                spec = KRW_CROSS[sym]
                all_tickers.extend(t for t in (spec["num"], spec["den"]) if t)
            else:
                all_tickers.append(sym)
    all_tickers = list(dict.fromkeys(all_tickers))

    try:
        data = yf.download(
            all_tickers, period="5d", auto_adjust=True,
            progress=False, threads=True,
        )
    except Exception:
        return results, fetched_at

    def _close_of(ticker: str):
        try:
            return data['Close'].dropna() if len(all_tickers) == 1 else data['Close'][ticker].dropna()
        except Exception:
            return None

    for group_key, group in MARKET_INDICES.items():
        for sym, name, decimals in group["items"]:
            try:
                if sym in KRW_CROSS:
                    close_series = _krw_cross_series(_close_of, sym)
                    if close_series is None:
                        continue
                else:
                    close_series = _close_of(sym)
                    if close_series is None:
                        continue
                close_series = close_series.dropna()
                if len(close_series) < 2:
                    continue
                price = float(close_series.iloc[-1])
                prev = float(close_series.iloc[-2])
                change = price - prev
                change_pct = (change / prev) * 100
                results[sym] = {
                    "name": name, "price": price, "change": change,
                    "change_pct": change_pct, "decimals": decimals,
                }
            except Exception:
                continue
    return results, fetched_at


KR_NAME_TO_TICKER = {
    "애플": "AAPL", "아이폰": "AAPL",
    "마이크로소프트": "MSFT", "엠에스": "MSFT",
    "구글": "GOOGL", "알파벳": "GOOGL",
    "아마존": "AMZN",
    "메타": "META", "페이스북": "META",
    "엔비디아": "NVDA",
    "테슬라": "TSLA",
    "넷플릭스": "NFLX",
    "디즈니": "DIS",
    "나이키": "NKE",
    "코카콜라": "KO",
    "펩시": "PEP", "펩시코": "PEP",
    "맥도날드": "MCD",
    "스타벅스": "SBUX",
    "비자": "V",
    "마스터카드": "MA",
    "존슨앤존슨": "JNJ",
    "프록터앤갬블": "PG",
    "월마트": "WMT",
    "코스트코": "COST",
    "보잉": "BA",
    "인텔": "INTC",
    "AMD": "AMD", "에이엠디": "AMD",
    "브로드컴": "AVGO",
    "퀄컴": "QCOM",
    "텍사스인스트루먼트": "TXN",
    "어도비": "ADBE",
    "세일즈포스": "CRM",
    "오라클": "ORCL",
    "시스코": "CSCO",
    "아이비엠": "IBM", "IBM": "IBM",
    "팔란티어": "PLTR",
    "스노우플레이크": "SNOW",
    "크라우드스트라이크": "CRWD",
    "우버": "UBER",
    "에어비앤비": "ABNB",
    "스포티파이": "SPOT",
    "쇼피파이": "SHOP",
    "줌": "ZM", "줌비디오": "ZM",
    "페이팔": "PYPL",
    "블록": "SQ", "스퀘어": "SQ",
    "로빈후드": "HOOD",
    "코인베이스": "COIN",
    "리비안": "RIVN",
    "루시드": "LCID",
    "소파이": "SOFI",
    "램리서치": "LRCX",
    "어플라이드머티어리얼즈": "AMAT", "어플라이드": "AMAT",
    "ASML": "ASML", "에이에스엠엘": "ASML",
    "마이크론": "MU",
    "슈퍼마이크로": "SMCI",
    "아리스타네트웍스": "ANET",
    "서비스나우": "NOW",
    "워크데이": "WDAY",
    "몽고디비": "MDB",
    "데이터독": "DDOG",
    "유니티": "U",
    "로블록스": "RBLX",
    "일라이릴리": "LLY",
    "화이자": "PFE",
    "머크": "MRK",
    "애브비": "ABBV",
    "암젠": "AMGN",
    "모더나": "MRNA",
    "유나이티드헬스": "UNH",
    "버크셔해서웨이": "BRK-B", "버크셔": "BRK-B",
    "제이피모건": "JPM", "JP모건": "JPM",
    "골드만삭스": "GS",
    "모건스탠리": "MS",
    "뱅크오브아메리카": "BAC",
    "웰스파고": "WFC",
    "찰스슈왑": "SCHW",
    "블랙록": "BLK",
    "아메리칸익스프레스": "AXP", "아멕스": "AXP",
    "시티그룹": "C", "시티": "C",
    "엑슨모빌": "XOM",
    "셰브론": "CVX",
    "록히드마틴": "LMT",
    "레이시온": "RTX",
    "캐터필러": "CAT",
    "3M": "MMM", "쓰리엠": "MMM",
    "허니웰": "HON",
    "제너럴일렉트릭": "GE", "GE": "GE",
    "포드": "F",
    "제너럴모터스": "GM", "GM": "GM",
    "홈디포": "HD",
    "로우스": "LOW",
    "타겟": "TGT",
    "달러제너럴": "DG",
    "크로거": "KR",
    "AT&T": "T", "에이티앤티": "T",
    "버라이즌": "VZ",
    "티모바일": "TMUS",
    "컴캐스트": "CMCSA",
    "넥스트에라에너지": "NEE",
    "서던컴퍼니": "SO",
    "듀크에너지": "DUK",
    "리얼티인컴": "O",
    "아메리칸타워": "AMT",
    "프롤로지스": "PLD",
    "ARM": "ARM", "에이알엠": "ARM", "암": "ARM",
    "팔로알토": "PANW", "팔로알토네트웍스": "PANW",
    "지스케일러": "ZS",
    "포티넷": "FTNT",
    "델": "DELL", "델테크놀로지": "DELL",
    "HP": "HPQ", "에이치피": "HPQ",
    "트위터": "X",
    "핀터레스트": "PINS",
    "스냅": "SNAP", "스냅챗": "SNAP",
    "레딧": "RDDT",
    "앱러빈": "APP",
    "덱스컴": "DXCM",
    "인튜이티브서지컬": "ISRG",
    "일루미나": "ILMN",
    "도미노피자": "DPZ",
    "치폴레": "CMG",
    "힐튼": "HLT",
    "마리어트": "MAR",
}

