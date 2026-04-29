#!/usr/bin/env python3
"""
한국 주식 시스템 수정 사항 테스트

주요 테스트 항목:
1. 티커 검증 및 자동 수정
2. 통화 자동 감지
3. ML 파이프라인
4. 신호 강도 및 신뢰도 계산
5. 경고 메시지 처리
"""

import json
import sys
from datetime import datetime


def test_ticker_validation():
    """티커 검증 테스트"""
    print("\n" + "="*60)
    print("티커 검증 테스트")
    print("="*60)

    from stock_analyzer.ticker_validator import validate_ticker, get_market_info, fix_common_ticker_errors

    test_cases = [
        ("005930.KS", True, "삼성전자 (정상)"),
        ("0126Z0.KS", True, "특수 한국 티커 (알파벳 포함)"),
        ("012620.KS", True, "동원산업 (정상)"),
        ("035420", False, "네이버 (suffix 누락)"),
        ("AAPL", True, "애플 (미국)"),
    ]

    for ticker, expected_valid, description in test_cases:
        is_valid, fixed, error = validate_ticker(ticker)
        market = get_market_info(ticker if is_valid else (fixed or ticker))

        print(f"\n{ticker}: {description}")
        print(f"  유효성: {'✓' if is_valid else '✗'} (예상: {'✓' if expected_valid else '✗'})")
        if fixed:
            print(f"  자동 수정: {fixed}")
        if error:
            print(f"  오류: {error}")
        print(f"  시장: {market['market']}, 통화: {market['currency']}")

        # 자동 수정 테스트
        if not is_valid and not fixed:
            auto_fixed = fix_common_ticker_errors(ticker)
            if auto_fixed:
                print(f"  자동 수정 시도: {auto_fixed}")


def test_ml_pipeline():
    """ML 파이프라인 테스트"""
    print("\n" + "="*60)
    print("ML 파이프라인 테스트")
    print("="*60)

    try:
        from stock_analyzer.ml_pipeline_fix import enhanced_ml_ensemble
        from chart_agent_service.data_collector import fetch_ohlcv, calculate_indicators
        import yfinance as yf

        # 한국 주식 테스트
        ticker = "005930.KS"  # 삼성전자
        print(f"\n테스트 종목: {ticker}")

        df = fetch_ohlcv(ticker)
        if df is None or df.empty:
            print("  ✗ 데이터 수집 실패")
            return

        print(f"  데이터 크기: {len(df)} rows")
        df = calculate_indicators(df)

        result = enhanced_ml_ensemble(ticker, df, debug=False)

        print(f"  모델 수: {result['ensemble']['model_count']}")
        print(f"  예측: {result['ensemble']['prediction']}")
        print(f"  상승 확률: {result['ensemble']['up_probability']:.1%}")
        print(f"  신호: {result['ensemble']['signal']}")
        print(f"  신뢰도: {result['ensemble']['confidence']}")

        if result['warnings']:
            print(f"  경고: {result['warnings']}")

        # 데이터 품질 체크
        quality = result.get('data_quality', {})
        if quality:
            print(f"  데이터 품질: {quality.get('data_quality', 'unknown')}")
            print(f"  총 행수: {quality.get('total_rows', 0)}")

    except Exception as e:
        print(f"  ✗ ML 파이프라인 테스트 실패: {e}")


def test_multi_agent():
    """멀티에이전트 시스템 테스트"""
    print("\n" + "="*60)
    print("멀티에이전트 시스템 테스트")
    print("="*60)

    try:
        from stock_analyzer.multi_agent import MultiAgentOrchestrator

        # 테스트 케이스
        test_tickers = [
            "005930.KS",  # 삼성전자 (정상)
            "0126Z0.KS",  # 오류 티커 (자동 수정 테스트)
        ]

        orchestrator = MultiAgentOrchestrator()

        for ticker in test_tickers:
            print(f"\n테스트 종목: {ticker}")
            print("-" * 40)

            result = orchestrator.analyze(ticker)

            # 기본 정보
            print(f"최종 티커: {result['ticker']}")

            # 시장 정보
            market = result.get('market_info', {})
            if market:
                print(f"시장: {market.get('market')}, 통화: {market.get('currency')}")

            # 경고
            warnings = result.get('warnings')
            if warnings:
                print(f"경고:")
                for w in warnings:
                    print(f"  - {w}")

            # 최종 결정
            decision = result.get('final_decision', {})
            if decision:
                print(f"\n최종 결정:")
                print(f"  신호: {decision.get('final_signal')}")
                print(f"  신뢰도: {decision.get('final_confidence')}")
                print(f"  통화: {decision.get('currency', 'N/A')}")

                # 신호 강도
                strength = decision.get('signal_strength', {})
                if strength:
                    print(f"  신호 강도: {strength.get('strength_level')}")
                    print(f"  총점: {strength.get('total_score', 0):+.1f}")

                # ML 정보
                ml_info = strength.get('ml_adjusted', {})
                if ml_info and ml_info.get('note'):
                    print(f"  ML: {ml_info['note']}")

                # 리스크
                risks = decision.get('key_risks', [])
                if risks:
                    print(f"  리스크:")
                    for r in risks:
                        print(f"    - {r}")

            # 에러 체크
            if result.get('error'):
                print(f"  ✗ 에러: {result['error']}")

            # 데이터 품질
            quality = result.get('data_quality', {})
            if quality:
                print(f"  데이터: {quality.get('total_rows', 0)} rows")

    except Exception as e:
        print(f"  ✗ 멀티에이전트 테스트 실패: {e}")
        import traceback
        traceback.print_exc()


def test_confidence_calculation():
    """신뢰도 계산 테스트"""
    print("\n" + "="*60)
    print("신뢰도 계산 테스트")
    print("="*60)

    # 테스트 시나리오
    test_cases = [
        (35, "very_strong", "매우 강한 신호"),
        (25, "strong", "강한 신호"),
        (14, "moderate", "보통 신호 (보고서 케이스)"),
        (7, "weak", "약한 신호"),
        (3, "very_weak", "매우 약한 신호"),
    ]

    print("\n총점 -> 신호 강도 매핑 테스트:")
    for score, expected_level, description in test_cases:
        # 신호 강도 판정 로직
        abs_score = abs(score)
        if abs_score > 30:
            level = "very_strong"
        elif abs_score > 20:
            level = "strong"
        elif abs_score > 10:
            level = "moderate"
        elif abs_score > 5:
            level = "weak"
        else:
            level = "very_weak"

        status = "✓" if level == expected_level else "✗"
        print(f"  점수 {score:+3d} → {level:12s} {status} ({description})")


def main():
    """메인 테스트 실행"""
    print("=" * 60)
    print("한국 주식 시스템 수정 사항 테스트")
    print("=" * 60)
    print(f"실행 시각: {datetime.now()}")

    # 1. 티커 검증
    test_ticker_validation()

    # 2. ML 파이프라인
    test_ml_pipeline()

    # 3. 신뢰도 계산
    test_confidence_calculation()

    # 4. 멀티에이전트 (전체 통합)
    test_multi_agent()

    print("\n" + "=" * 60)
    print("테스트 완료")
    print("=" * 60)


if __name__ == "__main__":
    main()