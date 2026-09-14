"""티커 표기·검증·워치리스트.

`webui.py` 분해 4단계 (CLAUDE.md §6-10). 종목 코드 정규화, 화면 표기 라벨, 워치리스트
파일 I/O 를 담는다.

워치리스트 저장은 **되읽기 검증**을 한다 — ro 마운트에서 조용히 실패해 "삭제됨"으로
보이던 사고가 있었다 (#24).
"""

from __future__ import annotations

import os
import re
from typing import Dict, Tuple

import streamlit as st

from ui.api_client import api_post, log_action

# 한국 주식 코드 패턴: 6자리 숫자(072130) 또는 4자리숫자+알파벳+숫자(0126Z0)
_KR_CODE_PATTERN = re.compile(r"^(?:\d{6}|\d{4}[A-Z]\d)$")

_ANALYZER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHLIST_PATH = os.path.join(_ANALYZER_DIR, "watchlist.txt")

try:
    from korean_stocks import KoreanStockData

    _KOREAN_STOCKS_AVAILABLE = True
except ImportError:
    _KOREAN_STOCKS_AVAILABLE = False

from ui.market import KR_NAME_TO_TICKER

from app_logging import get_logger

logger = get_logger("stock_auto.ui.tickers")

_KR_LOOKUP = {k.lower(): v for k, v in KR_NAME_TO_TICKER.items()}


def resolve_ticker(user_input: str) -> tuple[str, str]:
    text = user_input.strip()
    if not text:
        return "", ""

    upper = text.upper()
    if upper.isascii() and len(upper) <= 10:
        is_plain_kr_code = (
            (upper.isdigit() and len(upper) == 6)
            or (len(upper) == 6 and upper[:4].isdigit() and upper[4].isalpha() and upper[5].isdigit())
        )
        if is_plain_kr_code:
            try:
                normalized, _market = normalize_ticker(upper, "KR")
            except Exception:
                normalized = f"{upper}.KS"
            return normalized, f"{text} → {normalized}"
        return upper, ""

    # 한글이 포함된 경우 ticker_suggestion 먼저 시도 (한국 주식 우선)
    if any(ord(char) >= 0xAC00 and ord(char) <= 0xD7A3 for char in text):
        try:
            from ticker_suggestion import suggest_ticker
            result = suggest_ticker(text)

            if result['found'] and result['best_match']:
                # 95% 이상 매치로 자동 선택
                ticker = result['best_match']
                name = result['suggestions'][0].get('name', text) if result['suggestions'] else text
                return ticker, f"{text} → {ticker} ({name})"
            elif result['found'] and result['suggestions']:
                # 첫 번째 제안 사용
                ticker = result['suggestions'][0]['ticker']
                name = result['suggestions'][0].get('name', text)
                return ticker, f"{text} → {ticker} ({name})"
        except Exception as e:
            logger.error(f"ticker_suggestion 오류: {e}")

    # 기존 미국 주식 한글 매핑 확인
    query = text.lower()

    exact = _KR_LOOKUP.get(query)
    if exact:
        return exact, f"{text} → {exact}"

    best_match = None
    best_len = 0
    for name, ticker in _KR_LOOKUP.items():
        if name == query or query == name:
            return ticker, f"{text} → {ticker}"
        if query.startswith(name) or name.startswith(query):
            if len(name) > best_len:
                best_match = (ticker, name)
                best_len = len(name)

    # yfinance 검색 (미국 주식 위주)
    try:
        import yfinance as _yf
        results = _yf.Search(text, max_results=3)
        quotes = results.quotes if hasattr(results, 'quotes') else []
        if quotes:
            best = quotes[0]
            sym = best.get("symbol", "")
            sname = best.get("shortname", best.get("longname", ""))
            if sym:
                return sym, f"{text} → {sym} ({sname})"
    except Exception:
        pass

    if best_match:
        return best_match[0], f"{text} → {best_match[0]} ({best_match[1]})"

    return text, ""


try:
    from ticker_manager import normalize_ticker
except ImportError:  # 한국 주식 모듈 부재 시 접미사 규칙만 적용
    def normalize_ticker(code, market="KR"):  # type: ignore[misc]
        return (f"{code}.KS", market)

def _is_korean_ticker(ticker: str) -> bool:
    """
    한국 주식 판별. .KS/.KQ 접미사 또는 코드 패턴 기반.

    유엔젤(072130.KQ) 같은 종목을 접미사 없이 072130으로 저장해도
    정확하게 한국 주식으로 인식합니다.
    """
    if not ticker:
        return False
    t = ticker.upper().strip()
    if t.endswith(".KS") or t.endswith(".KQ"):
        # 접미사 제거 후 패턴 검사 (예: 072130.KQ → 072130)
        code = t[:-3]
        return bool(_KR_CODE_PATTERN.match(code))
    return bool(_KR_CODE_PATTERN.match(t))


def _market_flag(ticker: str) -> str:
    """티커에서 시장 플래그 반환 (🇰🇷 / 🇺🇸)."""
    return "🇰🇷" if _is_korean_ticker(ticker) else "🇺🇸"


# 주요 한국 종목 이름 폴백 맵 (pykrx/FDR 미설치 환경에서 기본 제공)
# yfinance는 영문명을 주거나 깨진 응답을 주는 경우가 많아 한글명 보장용
_KR_TICKER_NAME_FALLBACK = {
    "005930": "삼성전자", "000660": "SK하이닉스", "035420": "NAVER",
    "035720": "카카오", "051910": "LG화학", "006400": "삼성SDI",
    "005380": "현대차", "207940": "삼성바이오로직스", "000270": "기아",
    "068270": "셀트리온", "136480": "하림", "003380": "하림지주",
    "012330": "현대모비스", "066570": "LG전자", "033780": "KT&G",
    "015760": "한국전력", "105560": "KB금융", "055550": "신한지주",
    "086790": "하나금융지주", "096770": "SK이노베이션", "034730": "SK",
    "032830": "삼성생명", "017670": "SK텔레콤", "030200": "KT",
    "138040": "메리츠금융지주", "251270": "넷마블", "259960": "크래프톤",
    "018260": "삼성에스디에스", "006800": "미래에셋증권", "028260": "삼성물산",
    "010130": "고려아연", "011200": "HMM", "009150": "삼성전기",
    "267250": "HD현대중공업", "010950": "S-Oil", "161890": "한국콜마",
    "047050": "포스코인터내셔널", "028050": "삼성E&A", "036570": "엔씨소프트",
    "352820": "하이브", "0126Z0": "삼성에피스홀딩스",
}


@st.cache_data(ttl=3600, show_spinner=False)


def get_ticker_display_name(ticker: str) -> str:
    """
    티커 → 종목명 변환. 실패 시 티커 그대로 반환.

    다중 소스 폴백:
    1. 한국 주식: pykrx → FinanceDataReader → 내장 맵 → yfinance
    2. 미국 주식: yfinance shortName/longName
    3. 실패 시: 티커 원본

    1시간 세션 캐시로 반복 호출 최소화.
    """
    if not ticker:
        return ""
    t = ticker.upper().strip()

    # 한국 주식: 종목코드 추출
    code = None
    if _is_korean_ticker(t):
        if t.endswith(".KS") or t.endswith(".KQ"):
            code = t[:-3]
        else:
            code = t

    # ─── 한국 주식: korean_stocks_database.json 최우선 확인 ───
    if code:
        try:
            import os
            import json
            db_file = os.path.join(os.path.dirname(__file__), 'korean_stocks_database.json')
            if os.path.exists(db_file):
                with open(db_file, 'r', encoding='utf-8') as f:
                    db_data = json.load(f)
                    stocks = db_data.get('stocks', {})
                    if code in stocks:
                        return stocks[code]['name']
        except Exception:
            pass

        # ─── 한국 주식: ticker_suggestion 모듈 시도 ───
        try:
            from ticker_suggestion import suggest_ticker
            result = suggest_ticker(code, max_results=1)
            if result['found'] and result['suggestions']:
                suggestion = result['suggestions'][0]
                if suggestion['score'] >= 0.95:  # 95% 이상 매치만 신뢰
                    return suggestion['name']
        except Exception:
            pass

        # ─── 한국 주식: pykrx 시도 (빠르고 정확) ───
        try:
            from pykrx import stock as _krx
            name = _krx.get_market_ticker_name(code)
            if name and name.strip() and name != code:
                return name.strip()
        except Exception:
            pass

        # ─── 한국 주식: FinanceDataReader ───
        try:
            import FinanceDataReader as _fdr
            krx_list = _fdr.StockListing('KRX')
            # Symbol 또는 Code 컬럼
            sym_col = 'Symbol' if 'Symbol' in krx_list.columns else (
                'Code' if 'Code' in krx_list.columns else None
            )
            if sym_col:
                match = krx_list[krx_list[sym_col].astype(str) == code]
                name_col = None
                for col in ('Name', '종목명', 'CompanyName'):
                    if col in krx_list.columns:
                        name_col = col
                        break
                if not match.empty and name_col:
                    name = str(match.iloc[0][name_col]).strip()
                    if name and name != code:
                        return name
        except Exception:
            pass

        # ─── 한국 주식: 내장 fallback 맵 (pykrx/FDR 미설치 환경 대비) ───
        if code in _KR_TICKER_NAME_FALLBACK:
            return _KR_TICKER_NAME_FALLBACK[code]

        # ─── 한국 주식: korean_stocks 모듈 시도 ───
        if _KOREAN_STOCKS_AVAILABLE:
            try:
                collector = KoreanStockData()
                name = collector.get_stock_name(t)
                # yfinance가 깨진 응답을 줄 수 있음 — 티커 포함이면 거부
                if name and name != code and not _looks_broken_name(name, t, code):
                    return name
            except Exception:
                pass

    # ─── 미국 주식 / 폴백: yfinance ───
    try:
        import yfinance as yf
        info = yf.Ticker(t).info or {}
        # shortName이 longName보다 더 짧고 깔끔한 경우가 많음
        for key in ('shortName', 'longName'):
            name = info.get(key)
            if name and not _looks_broken_name(str(name), t, code):
                return str(name).strip()
    except Exception:
        pass

    # 모두 실패: 티커 그대로
    return t


def _looks_broken_name(name: str, ticker: str, code: str = None) -> bool:
    """yfinance가 돌려주는 깨진 응답 감지.

    예: "136480.KS,0P0000T1HA,516440" 같은 ticker/ID 나열 형태.
    """
    if not name:
        return True
    name_s = name.strip()
    # 티커나 코드가 이름에 포함되면 깨진 응답 의심
    if ticker and ticker in name_s:
        return True
    if code and code in name_s:
        return True
    # 콤마로 구분된 3개 이상 토큰이면 ID 나열일 가능성 농후
    if name_s.count(',') >= 2:
        return True
    return False


def format_ticker_label(ticker: str, style: str = "name_with_code") -> str:
    """
    표시용 라벨 생성.

    style:
      "name_with_code" (기본) - "하림 (136480.KS)"
      "name_only"             - "하림"
      "code_only"             - "136480.KS"
      "compact"               - "하림 · 136480.KS"
      "flag_name"             - "🇰🇷 하림"
      "flag_name_code"        - "🇰🇷 하библi(136480.KS)"
    """
    if not ticker:
        return ""
    name = get_ticker_display_name(ticker)
    flag = _market_flag(ticker)

    # 이름 조회 실패 시 티커만
    if not name or name == ticker:
        if style.startswith("flag_"):
            return f"{flag} {ticker}"
        return ticker

    if style == "name_only":
        return name
    if style == "code_only":
        return ticker
    if style == "compact":
        return f"{name} · {ticker}"
    if style == "flag_name":
        return f"{flag} {name}"
    if style == "flag_name_code":
        return f"{flag} {name} ({ticker})"
    # default: name_with_code
    return f"{name} ({ticker})"


def _market_code(ticker: str) -> str:
    """
    티커에서 시장 코드 반환 (KOSPI / KOSDAQ / KR / US).

    - `.KS` → KOSPI
    - `.KQ` → KOSDAQ
    - 접미사 없는 한국 6자리 코드 → 'KR' (KOSPI/KOSDAQ 확정 불가)
    - 그 외 → US
    """
    t = (ticker or "").upper().strip()
    if t.endswith(".KS"):
        return "KOSPI"
    if t.endswith(".KQ"):
        return "KOSDAQ"
    if _is_korean_ticker(t):
        return "KR"
    return "US"


def load_watchlist() -> list[str]:
    if not os.path.exists(WATCHLIST_PATH):
        return []
    result = []
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            if raw.isascii():
                result.append(raw.upper())
            else:
                ticker, _ = resolve_ticker(raw)
                result.append(ticker if ticker else raw)
    return sorted(result)  # 알파벳 순으로 정렬


def save_watchlist(tickers: list[str]):
    """워치리스트를 파일에 기록하고 반영을 재확인한다.

    2026-08-03: 삭제가 UI에서는 반영된 듯 보이는데 파일은 그대로여서
    새로고침하면 종목이 되살아나는 일이 있었다(사용자 액션 로그에는 remove가
    남았지만 파일 mtime은 그 이전). 쓰기 실패를 조용히 넘기면 원인 추적이
    불가능하므로, 기록 후 되읽어 검증하고 불일치면 예외를 올린다.
    """
    header = (
        "# 관심 종목 리스트 (SSOT: WebUI/백엔드/배치 스크립트 공용)\n"
        "# 한 줄에 하나, #은 주석, 빈 줄은 무시됨\n"
        "# 편집 권장 방법: WebUI 사이드바 → 관심 종목 관리\n"
        "# 직접 편집 시 WebUI 재시작 또는 새로고침 필요\n\n"
    )
    expected = sorted({t.strip().upper() for t in tickers if t and t.strip()})
    with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
        f.write(header)
        for t in expected:
            f.write(f"{t}\n")
        f.flush()
        os.fsync(f.fileno())

    persisted = sorted(
        line.strip().upper()
        for line in open(WATCHLIST_PATH, encoding="utf-8")
        if line.strip() and not line.startswith("#")
    )
    if persisted != expected:
        raise IOError(
            f"워치리스트 저장 검증 실패: 기대 {len(expected)}종목 / 실제 {len(persisted)}종목 "
            f"({WATCHLIST_PATH})"
        )


def clear_watchlist() -> tuple[bool, str]:
    """워치리스트 전체 비우기."""
    removed = len(load_watchlist())
    if removed == 0:
        return False, "이미 비어 있습니다"
    save_watchlist([])
    log_action("watchlist_edit", metadata={"op": "clear", "removed": removed})
    return True, f"{removed}개 종목을 모두 삭제했습니다"


_TICKER_VALIDATION_CACHE: Dict[str, Tuple[bool, str]] = {}


def validate_ticker_webui(ticker: str) -> tuple[bool, str]:
    """
    [WebUI 전용] 종목 코드 유효성 검증 - yfinance 실시간 조회 + 한글 이름 검색 포함.

    참고: 백엔드 포맷 검증은 `stock_analyzer.ticker_validator.validate_ticker()`를 사용하세요.
    이 함수는 UI 표시용 메시지를 함께 반환하기 위해 별도로 유지됩니다.
    같은 입력에 대해서는 세션 캐시를 사용해 반복 yfinance 호출을 피합니다.
    Returns: (is_valid, message)
    """
    ticker_input = ticker.strip()
    ticker = ticker_input.upper()

    # 캐시 조회 (세션 내 반복 검증 시 UI 블로킹 방지)
    cache_key = ticker_input
    if cache_key in _TICKER_VALIDATION_CACHE:
        return _TICKER_VALIDATION_CACHE[cache_key]

    result = _validate_ticker_webui_impl(ticker_input, ticker)
    # 긍정 결과만 캐싱 (부정 결과는 일시적 네트워크 장애일 수 있음)
    if result[0]:
        _TICKER_VALIDATION_CACHE[cache_key] = result
    return result


def _validate_ticker_webui_impl(ticker_input: str, ticker: str) -> tuple[bool, str]:

    # 기본 형식 검증
    if not ticker:
        return False, "종목 코드를 입력하세요"

    # 한국 주식 이름 검색 (한글이 포함된 경우)
    if any(ord(char) >= 0xAC00 and ord(char) <= 0xD7A3 for char in ticker_input):
        try:
            from ticker_suggestion import suggest_ticker

            # 개선된 ticker_suggestion 사용
            result = suggest_ticker(ticker_input)

            if result['found'] and result['best_match']:
                # 95% 이상 매치로 자동 선택된 경우
                ticker = result['best_match']
                logger.info(f"✅ 종목 자동 선택: {result['suggestions'][0]['name']} ({ticker})")
            elif result['found'] and result['suggestions']:
                # 여러 제안이 있는 경우 첫번째 사용 (또는 UI에서 선택하게 할 수 있음)
                ticker = result['suggestions'][0]['ticker']
                logger.info(f"✅ 종목 선택: {result['suggestions'][0]['name']} ({ticker})")
            else:
                return False, f"❌ '{ticker_input}'를 찾을 수 없습니다. 정확한 종목명이나 종목코드를 입력하세요."
        except Exception as e:
            logger.error(f"한국 주식 이름 검색 오류: {e}")

    if len(ticker) > 10:  # 대부분의 티커는 10자 이내
        return False, f"종목 코드가 너무 깁니다: {ticker}"

    # 한국 주식 코드 자동 감지 (6자리 숫자 또는 특수 코드 0126Z0 형식)
    import re
    if (ticker.isdigit() and len(ticker) == 6) or re.match(r'^[0-9]{4}[A-Z][0-9]$', ticker):
        # KOSPI (.KS) 또는 KOSDAQ (.KQ) 자동 시도
        import yfinance as yf

        valid_markets = []

        # 두 시장 모두 확인
        for suffix in ['.KS', '.KQ']:
            test_ticker = ticker + suffix
            try:
                stock = yf.Ticker(test_ticker)
                # UI 블로킹 최소화를 위해 2일만 조회 (존재 여부만 확인하면 충분)
                info = stock.history(period="2d")

                if not info.empty:
                    # 종목명 가져오기
                    try:
                        stock_info = stock.info
                        company_name = stock_info.get('longName', stock_info.get('shortName', ''))
                        market = "KOSPI" if suffix == '.KS' else "KOSDAQ"

                        # 유효한 이름이 있는 경우만 추가 (잘못된 데이터 필터링)
                        if company_name and not company_name.startswith(ticker):
                            valid_markets.append({
                                'ticker': test_ticker,
                                'name': company_name,
                                'market': market
                            })
                        elif not company_name:
                            # 이름이 없어도 데이터가 있으면 추가
                            valid_markets.append({
                                'ticker': test_ticker,
                                'name': 'N/A',
                                'market': market
                            })
                    except:
                        # info 가져오기 실패해도 데이터는 있음
                        market = "KOSPI" if suffix == '.KS' else "KOSDAQ"
                        valid_markets.append({
                            'ticker': test_ticker,
                            'name': 'N/A',
                            'market': market
                        })
            except:
                continue

        # 결과 처리
        if len(valid_markets) == 0:
            return False, f"❌ '{ticker}'는 유효하지 않은 한국 주식 코드입니다. KOSPI(.KS) 또는 KOSDAQ(.KQ) 모두에서 찾을 수 없습니다."
        elif len(valid_markets) == 1:
            m = valid_markets[0]
            if m['name'] != 'N/A':
                return True, f"✅ {m['ticker']} ({m['name']}, {m['market']})"
            else:
                return True, f"✅ {m['ticker']} ({m['market']})"
        else:
            # 두 시장 모두에 있는 경우
            options = []
            for m in valid_markets:
                if m['name'] != 'N/A':
                    options.append(f"{m['ticker']} ({m['name']}, {m['market']})")
                else:
                    options.append(f"{m['ticker']} ({m['market']})")

            # KOSDAQ을 우선 선택 (일반적으로 더 많은 신규 기업)
            kosdaq_option = next((m for m in valid_markets if m['market'] == 'KOSDAQ'), None)
            if kosdaq_option:
                selected = kosdaq_option
            else:
                selected = valid_markets[0]

            msg = f"✅ {selected['ticker']}"
            if selected['name'] != 'N/A':
                msg += f" ({selected['name']}, {selected['market']})"
            else:
                msg += f" ({selected['market']})"
            msg += f"\n⚠️ 참고: {ticker}는 두 시장에 모두 존재합니다: " + " / ".join(options)

            return True, msg

    # Yahoo Finance에서 실제 데이터 존재 여부 확인
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info = stock.history(period="5d")

        if info.empty:
            return False, f"❌ '{ticker}'는 유효하지 않은 종목 코드입니다. Yahoo Finance에서 데이터를 찾을 수 없습니다."

        # 추가 정보 가져오기 시도
        try:
            stock_info = stock.info
            company_name = stock_info.get('longName', stock_info.get('shortName', ''))
            if company_name:
                return True, f"✅ {ticker} ({company_name})"
            else:
                return True, f"✅ {ticker}"
        except:
            return True, f"✅ {ticker}"

    except Exception as e:
        return False, f"❌ '{ticker}' 검증 실패: 유효하지 않은 종목 코드이거나 네트워크 오류입니다."


def add_to_watchlist(ticker: str) -> tuple[bool, str]:
    ticker = ticker.strip().upper()
    if not ticker:
        return False, "종목 코드를 입력하세요"

    # 기본 문자 검증
    if not ticker.replace('.', '').replace('-', '').replace('^', '').replace('=', '').isalnum():
        return False, f"❌ 잘못된 형식: '{ticker}'"

    # 실제 종목 유효성 검증
    is_valid, message = validate_ticker_webui(ticker)
    if not is_valid:
        return False, message

    # 한국 주식의 경우 자동 해결된 ticker를 추출
    resolved_ticker = ticker
    import re
    # 6자리 숫자 또는 특수 코드 (예: 0126Z0) 처리
    if ((ticker.isdigit() and len(ticker) == 6) or
        re.match(r'^[0-9]{4}[A-Z][0-9]$', ticker)) and "✅" in message:
        # 메시지에서 실제 ticker 추출 (예: "✅ 072130.KQ (유엔젤, KOSDAQ)")
        match = re.search(r'✅\s+(\S+)\s+\(', message)
        if match:
            resolved_ticker = match.group(1)

    # Watchlist에 추가
    current = load_watchlist()
    if resolved_ticker in current:
        return False, f"⚠️ {resolved_ticker}는 이미 Watchlist에 있습니다"

    current.append(resolved_ticker)
    try:
        save_watchlist(current)
    except OSError as exc:
        return False, f"❌ {resolved_ticker} 추가 실패 — 파일 저장 오류: {exc}"
    log_action("watchlist_edit", ticker=resolved_ticker, metadata={"op": "add"})

    # 성공 메시지에 회사명 포함
    if "✅" in message:
        return True, f"{message.replace('✅', '➕')} - Watchlist에 추가됨"
    else:
        return True, f"➕ {resolved_ticker} added to Watchlist"


def remove_from_watchlist(ticker: str) -> tuple[bool, str]:
    ticker = ticker.strip().upper()
    current = load_watchlist()
    if ticker not in current:
        return False, f"{ticker} not found"
    current.remove(ticker)
    try:
        save_watchlist(current)
    except OSError as exc:
        # 저장 실패를 성공으로 보고하면 새로고침 때 종목이 되살아나 혼란만 남는다.
        return False, f"❌ {ticker} 삭제 실패 — 파일 저장 오류: {exc}"
    log_action("watchlist_edit", ticker=ticker, metadata={"op": "remove"})
    return True, f"{ticker} removed"
