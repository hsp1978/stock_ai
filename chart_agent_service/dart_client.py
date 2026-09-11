"""
DART(전자공시시스템) API 클라이언트 (P2).

OpenDartReader를 사용해 한국 상장기업 공시를 조회한다.
DART_API_KEY 미설정·라이브러리 미설치 등 '조회 불가' 상태는 DartUnavailable로
올린다 — 빈 리스트('공시 0건')와 섞이면 장애가 정상으로 위장된다.

주요 기능:
- get_corp_code(): 종목코드 → DART 고유번호 변환
- fetch_recent_disclosures(): 최근 N일 공시 목록
- classify_disclosure(): 공시 유형 분류 (호재/악재/중립)
- fetch_insider_trades(): 임원·주요주주 특정증권등 소유상황보고 (elestock)
- score_insider_trades(): 소유변동 → 신호/점수
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# OpenDartReader는 CWD의 docs_cache/에 날짜별 corpCode 스냅샷(약 8MB)을 남긴다.
# 매일 새 파일이 쌓이므로 사용 시점에 오래된 것을 정리한다 (CLAUDE.md #7).
_CORP_CACHE_DIR = "docs_cache"
_CORP_CACHE_KEEP = 2
_cache_pruned = False


def _prune_corp_code_cache() -> None:
    """docs_cache/의 날짜별 corpCode 스냅샷을 최신 N개만 남긴다. 프로세스당 1회."""
    global _cache_pruned
    if _cache_pruned:
        return
    _cache_pruned = True
    try:
        files = sorted(
            Path(_CORP_CACHE_DIR).glob("opendartreader_corp_codes_*.pkl"),
            key=lambda p: p.name,
            reverse=True,
        )
        for stale in files[_CORP_CACHE_KEEP:]:
            stale.unlink()
            logger.info("오래된 DART corpCode 캐시 삭제: %s", stale.name)
    except OSError as exc:  # 캐시 정리 실패가 공시 조회를 막아서는 안 된다
        logger.debug("corpCode 캐시 정리 건너뜀: %s", exc)


class DartUnavailable(RuntimeError):
    """조회 자체가 불가한 상태 — '공시 0건'과 구분해야 한다.

    2026-07-30 진단: 라이브러리 미설치(컨테이너)와 잘못된 API 사용(호스트)이
    둘 다 빈 리스트로 뭉개져 "최근 30일 공시 없음"으로 보고됐다. DART 공시
    도구는 방향성 도구라 조용히 score 0이 되면 신호를 희석한다.
    """


# 공시 유형 키워드 → 호재/악재
_POSITIVE_KEYWORDS = [
    "자사주",
    "배당",
    "무상증자",
    "자회사 설립",
    "신규 계약",
    "수주",
    "경영실적",
    "실적 호조",
    "최대 매출",
    "흑자",
    "영업이익 증가",
]
_NEGATIVE_KEYWORDS = [
    "불성실공시",
    "횡령",
    "배임",
    "영업정지",
    "조업중단",
    "대규모 손실",
    "소송",
    "행정처분",
    "제재",
    "주식거래 정지",
    "상장폐지 사유",
    "자산 매각",
    "유상증자",
]


def _get_dart_api_key() -> Optional[str]:
    key = os.getenv("DART_API_KEY", "")
    return key if key.strip() else None


def get_corp_code(ticker: str) -> Optional[str]:
    """
    6자리 종목코드 → DART 고유번호 변환.

    Args:
        ticker: "005930" 또는 "005930.KS" 형식

    Returns:
        DART 고유번호 8자리 문자열 (없으면 None)
    """
    api_key = _get_dart_api_key()
    if not api_key:
        logger.debug("DART_API_KEY 없음 — get_corp_code 건너뜀")
        return None

    try:
        # 이 패키지는 sys.modules 항목을 클래스로 치환한다 — `import OpenDartReader`가
        # 모듈이 아니라 클래스를 바인딩하므로 그대로 호출해야 한다.
        # `odr.OpenDartReader(...)`는 AttributeError, `from X import X`는 ImportError.
        import OpenDartReader  # type: ignore[import-untyped]

        code = ticker.upper().split(".")[0]  # "005930.KS" → "005930"
        dart = OpenDartReader(api_key)
        result = dart.find_corp_code(code)
        if result and len(result) > 0:
            return (
                str(result.iloc[0]["corp_code"])
                if hasattr(result, "iloc")
                else str(result)
            )
    except Exception as exc:
        logger.warning("get_corp_code(%s) 실패: %s", ticker, exc)
    return None


def fetch_recent_disclosures(
    ticker: str,
    days_back: int = 30,
    max_items: int = 10,
) -> list[dict]:
    """
    최근 N일 DART 공시 목록 조회.

    Args:
        ticker:     종목코드 (6자리 또는 "005930.KS")
        days_back:  조회 기간 (일)
        max_items:  최대 반환 건수

    Returns:
        공시 목록 [{rcept_no, rcept_dt, corp_name, report_nm, classified}]

    Raises:
        DartUnavailable: 라이브러리 미설치·인증 실패 등 조회 자체가 불가한 경우.
            빈 리스트('공시 없음')와 구분하기 위해 예외로 올린다.
    """
    api_key = _get_dart_api_key()
    if not api_key:
        raise DartUnavailable("DART_API_KEY 미설정")

    try:
        # 클래스 바인딩 주의 — get_corp_code 주석 참조.
        import OpenDartReader  # type: ignore[import-untyped]
    except ImportError as exc:
        raise DartUnavailable(f"OpenDartReader 미설치: {exc}") from exc

    _prune_corp_code_cache()

    try:
        code = ticker.upper().split(".")[0]
        dart = OpenDartReader(api_key)

        end_date = date.today()
        start_date = end_date - timedelta(days=days_back)

        df = dart.list(
            code,
            start=start_date.strftime("%Y%m%d"),
            end=end_date.strftime("%Y%m%d"),
            kind="A",  # 정기공시
        )
        if df is None or df.empty:
            # 비정기 공시도 조회
            df = dart.list(
                code,
                start=start_date.strftime("%Y%m%d"),
                end=end_date.strftime("%Y%m%d"),
            )

        if df is None or df.empty:
            return []

        results = []
        for _, row in df.head(max_items).iterrows():
            report_name = str(row.get("report_nm", ""))
            classified = classify_disclosure(report_name)
            results.append(
                {
                    "rcept_no": str(row.get("rcept_no", "")),
                    "rcept_dt": str(row.get("rcept_dt", "")),
                    "corp_name": str(row.get("corp_name", "")),
                    "report_nm": report_name,
                    "classified": classified,
                }
            )
        return results

    except ValueError as exc:
        # DART 기업목록에 없는 종목(ETF/ETN/리츠 등)은 영구 상태이지 장애가 아니다.
        # 조회 불가로 올리면 매 스캔마다 '장애'로 보고돼 실제 장애를 가린다.
        if "could not find" in str(exc).lower():
            logger.debug("fetch_recent_disclosures(%s): DART 미등록 종목", ticker)
            return []
        logger.warning("fetch_recent_disclosures(%s) 실패: %s", ticker, exc)
        raise DartUnavailable(f"ValueError: {exc}") from exc
    except Exception as exc:
        logger.warning("fetch_recent_disclosures(%s) 실패: %s", ticker, exc)
        raise DartUnavailable(f"{type(exc).__name__}: {exc}") from exc


def classify_disclosure(report_name: str) -> str:
    """
    공시 제목으로 호재/악재/중립 분류.

    Returns:
        "positive" | "negative" | "neutral"
    """
    for kw in _NEGATIVE_KEYWORDS:
        if kw in report_name:
            return "negative"
    for kw in _POSITIVE_KEYWORDS:
        if kw in report_name:
            return "positive"
    return "neutral"


def compute_disclosure_score(disclosures: list[dict]) -> dict:
    """
    공시 목록에서 시그널 점수와 요약을 산출한다.

    Returns:
        {"score": float, "signal": str, "positive": int, "negative": int,
         "neutral": int, "total": int, "recent_titles": list[str]}
    """
    pos = sum(1 for d in disclosures if d.get("classified") == "positive")
    neg = sum(1 for d in disclosures if d.get("classified") == "negative")
    neutral = len(disclosures) - pos - neg
    total = len(disclosures)

    # 기준: 호재-악재 차이를 0~10 범위로 매핑
    net = pos - neg
    score = max(-10.0, min(10.0, float(net) * 2.0))
    signal = "buy" if score > 1 else "sell" if score < -1 else "neutral"

    return {
        "score": round(score, 1),
        "signal": signal,
        "positive": pos,
        "negative": neg,
        "neutral": neutral,
        "total": total,
        "recent_titles": [d["report_nm"] for d in disclosures[:3]],
    }


# ═══════════════════════════════════════════════════════════════════
#  임원·주요주주 특정증권등 소유상황보고서 (elestock)
# ═══════════════════════════════════════════════════════════════════
#
# 2026-09 사후검증에서 이 데이터의 부재가 실손실로 확인됐다:
# 유엔젤(072130) 안갑대 이사가 2026-04-01 공시로 보유 12,002주를 전량 매도해
# **잔량 0주**가 됐고, 당시 Event Analyst 는 "내부자 거래 데이터도 없어 파악 불가"로
# 답했다. 그 시점 ~₩6,000대였던 주가는 2026-09-10 ₩3,510 (약 -42%).
# 데이터는 DART 에 있었고 조회하지 않았을 뿐이다.
#
# 핵심 필드는 증감수가 아니라 **거래 후 잔량**(`sp_stock_lmp_cnt`)이다.
# 일부 매도와 전량 이탈은 의미가 전혀 다르다.

_ELESTOCK_URL = "https://opendart.fss.or.kr/api/elestock.json"
_ELESTOCK_TIMEOUT = 10.0


@dataclass(frozen=True)
class InsiderTrade:
    """임원·주요주주 소유상황 보고 1건."""

    report_date: str            # rcept_dt (YYYY-MM-DD)
    reporter: str               # repror — 보고자
    position: str               # isu_exctv_ofcps — 직위
    registered: str             # isu_exctv_rgist_at — 등기/비등기
    is_major_holder: bool       # isu_main_shrholdr
    shares_after: Optional[int]  # sp_stock_lmp_cnt — 거래 후 잔량 (핵심)
    shares_delta: Optional[int]  # sp_stock_lmp_irds_cnt — 증감수 (음수=매도)
    ownership_pct: Optional[float]
    receipt_no: str

    @property
    def is_full_exit(self) -> bool:
        """전량 이탈 — 잔량 0 + 감소."""
        return (
            self.shares_after == 0
            and self.shares_delta is not None
            and self.shares_delta < 0
        )


def _to_int(value: Any) -> Optional[int]:
    """DART 수치는 콤마 포함 문자열이고 결측은 '-' 로 온다."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace(" ", "")
    if text in ("", "-", "None"):
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in ("", "-", "None"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=6),
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    reraise=True,
)
def _request_elestock(corp_code: str, api_key: str) -> dict:
    """elestock.json 원본 응답. 네트워크 오류는 tenacity 로 재시도."""
    resp = httpx.get(
        _ELESTOCK_URL,
        params={"crtfc_key": api_key, "corp_code": corp_code},
        timeout=_ELESTOCK_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_insider_trades(ticker: str, months: int = 6) -> list[InsiderTrade]:
    """임원·주요주주 소유상황 보고를 최근 `months` 개월분 반환 (최신순).

    Raises:
        DartUnavailable: API 키 미설정·고유번호 조회 실패·API 오류 등
            **조회 자체가 불가한 경우**. 빈 리스트('변동 없음')와 반드시 구분한다.
    """
    api_key = _get_dart_api_key()
    if not api_key:
        raise DartUnavailable("DART_API_KEY 미설정")

    corp_code = get_corp_code(ticker)
    if not corp_code:
        raise DartUnavailable(f"고유번호 조회 실패: {ticker}")

    try:
        payload = _request_elestock(corp_code, api_key)
    except Exception as exc:  # httpx/JSON 오류 — 사유를 버리지 않는다
        raise DartUnavailable(f"{type(exc).__name__}: {exc}") from exc

    status = str(payload.get("status") or "")
    # 013 = 조회된 데이터 없음 (정상 응답이며 '보고 없음'을 뜻한다)
    if status == "013":
        return []
    if status != "000":
        raise DartUnavailable(
            f"DART status={status} ({payload.get('message')})"
        )

    cutoff = date.today() - timedelta(days=int(months * 30.5))
    trades: list[InsiderTrade] = []
    for row in payload.get("list") or []:
        raw_date = str(row.get("rcept_dt") or "").strip()
        try:
            report_date = datetime.strptime(raw_date.replace(".", "-"), "%Y-%m-%d").date()
        except ValueError:
            continue
        if report_date < cutoff:
            continue
        major = str(row.get("isu_main_shrholdr") or "").strip()
        trades.append(
            InsiderTrade(
                report_date=report_date.isoformat(),
                reporter=str(row.get("repror") or "").strip(),
                position=str(row.get("isu_exctv_ofcps") or "").strip(),
                registered=str(row.get("isu_exctv_rgist_at") or "").strip(),
                is_major_holder=major not in ("", "-"),
                shares_after=_to_int(row.get("sp_stock_lmp_cnt")),
                shares_delta=_to_int(row.get("sp_stock_lmp_irds_cnt")),
                ownership_pct=_to_float(row.get("sp_stock_lmp_rate")),
                receipt_no=str(row.get("rcept_no") or "").strip(),
            )
        )
    trades.sort(key=lambda t: t.report_date, reverse=True)
    return trades


# 점수 스케일은 다른 도구와 같은 [-6, +8] 구간을 쓴다.
# 전량 이탈이 기간 매도의 이 비중 이상이고 순매도일 때만 최대 강도로 본다.
_EXIT_WEIGHT_FOR_CRITICAL = 0.5

_FULL_EXIT_SCORE = -5
_NET_SELL_SCORE = -3
_MILD_SELL_SCORE = -1
_NET_BUY_SCORE = 3
_MILD_BUY_SCORE = 1


@dataclass
class InsiderSignal:
    signal: str
    score: int
    detail: str
    full_exits: list[str] = field(default_factory=list)
    critical_risks: list[str] = field(default_factory=list)
    buy_shares: int = 0
    sell_shares: int = 0
    trade_count: int = 0


def score_insider_trades(trades: list[InsiderTrade]) -> InsiderSignal:
    """소유변동을 신호로 환산한다.

    전량 이탈(잔량 0)은 부분 매도와 다른 사건으로 취급한다 — 임원이 지분을 전부
    비우는 것은 '비중 축소'가 아니라 '이탈'이고, 유엔젤 사례에서 -42% 의 선행
    지표였다.
    """
    if not trades:
        return InsiderSignal("neutral", 0, "최근 임원·주요주주 소유변동 보고 없음")

    buy_shares = sum(t.shares_delta for t in trades if (t.shares_delta or 0) > 0)
    sell_shares = -sum(t.shares_delta for t in trades if (t.shares_delta or 0) < 0)
    exits = [t for t in trades if t.is_full_exit]

    net = buy_shares - sell_shares
    total = buy_shares + sell_shares

    if exits:
        names = [
            f"{t.reporter}({t.position or '직위미상'}) {t.report_date}"
            for t in exits
        ]
        exit_shares = sum(abs(t.shares_delta or 0) for t in exits)
        exit_weight = exit_shares / sell_shares if sell_shares else 0.0

        # 전량 이탈을 **무조건** 최대 강도로 읽으면 대형주에서 오탐이 쏟아진다.
        # 실측(2026-09-11): 삼성전자는 6개월 보고 837건에 순매수 +939,336주인데
        # 임원 1명이 937주(매도의 2.3%)를 비운 것이 전량 이탈로 잡힌다 — 퇴임성
        # 정리이고 매도 신호가 아니다. 유엔젤은 보고 2건 전부가 그 이탈이고
        # 순매도 -12,002주(매도의 100%)였다. 규모와 방향으로 구분한다.
        significant = net < 0 and exit_weight >= _EXIT_WEIGHT_FOR_CRITICAL
        if significant:
            return InsiderSignal(
                signal="strong_sell",
                score=_FULL_EXIT_SCORE,
                detail=(
                    f"내부자 전량 매도 {len(exits)}건 — 잔량 0주: {', '.join(names[:3])} "
                    f"(이탈 {exit_shares:,}주 = 기간 매도의 {exit_weight:.0%}, 순매도)"
                ),
                full_exits=names,
                critical_risks=[f"내부자 전량 매도(잔량 0주): {names[0]}"],
                buy_shares=buy_shares,
                sell_shares=sell_shares,
                trade_count=len(trades),
            )
        if net >= 0:
            # 이탈 사실은 리포트에 남기되, 같은 창의 순매수가 우세하면 신호로 쓰지 않는다.
            return InsiderSignal(
                signal="neutral",
                score=0,
                detail=(
                    f"내부자 전량 매도 {len(exits)}건({exit_shares:,}주) 있으나 "
                    f"기간 순매수 +{net:,}주 우세 — 개별 퇴임성 정리로 판단"
                ),
                full_exits=names,
                buy_shares=buy_shares,
                sell_shares=sell_shares,
                trade_count=len(trades),
            )
        return InsiderSignal(
            signal="sell",
            score=_NET_SELL_SCORE,
            detail=(
                f"내부자 순매도 {-net:,}주 (전량 이탈 {len(exits)}건 포함, "
                f"이탈 비중 {exit_weight:.0%})"
            ),
            full_exits=names,
            buy_shares=buy_shares,
            sell_shares=sell_shares,
            trade_count=len(trades),
        )

    if total == 0:
        detail = f"소유변동 보고 {len(trades)}건, 순증감 0주"
        signal, score = "neutral", 0
    elif net < 0:
        dominant = sell_shares / total
        signal = "sell"
        score = _NET_SELL_SCORE if dominant >= 0.7 else _MILD_SELL_SCORE
        detail = (
            f"내부자 순매도 {sell_shares - buy_shares:,}주 "
            f"(매도 {sell_shares:,} / 매수 {buy_shares:,}주, {len(trades)}건)"
        )
    elif net > 0:
        dominant = buy_shares / total
        signal = "buy"
        score = _NET_BUY_SCORE if dominant >= 0.7 else _MILD_BUY_SCORE
        detail = (
            f"내부자 순매수 {net:,}주 "
            f"(매수 {buy_shares:,} / 매도 {sell_shares:,}주, {len(trades)}건)"
        )
    else:
        signal, score = "neutral", 0
        detail = f"내부자 매수·매도 균형 ({len(trades)}건)"

    return InsiderSignal(
        signal=signal,
        score=score,
        detail=detail,
        buy_shares=buy_shares,
        sell_shares=sell_shares,
        trade_count=len(trades),
    )
