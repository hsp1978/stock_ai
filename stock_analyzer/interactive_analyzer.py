#!/usr/bin/env python3
"""
Interactive Stock Analyzer - 사용자 대화형 종목 분석

잘못된 종목 입력 시:
1. 유사 종목 추천
2. 사용자가 선택
3. 선택된 종목 분석
"""

import json
from typing import Dict, Optional
from stock_analyzer.multi_agent import MultiAgentOrchestrator
from stock_analyzer.ticker_suggestion import TickerSuggestion
from stock_analyzer.ticker_verifier import verify_and_validate


class InteractiveAnalyzer:
    """대화형 주식 분석기"""

    def __init__(self):
        self.orchestrator = MultiAgentOrchestrator()
        self.suggester = TickerSuggestion()

    def analyze_with_suggestion(
        self,
        input_text: str,
        auto_select: bool = True,
        auto_select_threshold: float = 0.95,
        max_suggestions: int = 5,
    ) -> Dict:
        """
        종목 분석 with 자동 추천

        Args:
            input_text: 사용자 입력 (티커 또는 회사명)
            auto_select: 임계값 이상 매치 시 자동 선택
            auto_select_threshold: 자동 선택 임계값 (CLI=0.95, WebUI=0.80 권장)
            max_suggestions: 수동 선택 시 반환할 최대 추천 개수

        Returns:
            분석 결과 또는 오류/추천 메시지
        """

        # 1. 먼저 입력된 텍스트 그대로 검증
        verification = verify_and_validate(input_text)

        if verification['exists'] and verification['can_analyze']:
            # 정확한 티커 - 바로 분석
            print(f"✅ 종목 확인: {verification['company_name']} ({input_text})")
            return self.orchestrator.analyze(input_text)

        # 2. 종목을 찾을 수 없으면 추천
        suggestions = self.suggester.find_suggestions(input_text, max_results=max_suggestions)

        if not suggestions:
            return {
                "error": "종목을 찾을 수 없습니다",
                "input": input_text,
                "message": "일치하거나 유사한 종목이 없습니다. 회사명(한/영), 티커(AAPL), 또는 한국 종목코드(005930.KS)를 다시 확인해주세요.",
                "suggestions": None
            }

        # 3. 자동 선택 체크 (임계값 이상 매치)
        if auto_select and suggestions[0]['score'] >= auto_select_threshold:
            selected_ticker = suggestions[0]['ticker']
            print(f"✅ 자동 선택: {suggestions[0]['name']} ({selected_ticker})")
            print(f"   매치율: {suggestions[0]['score']*100:.1f}%")
            return self.orchestrator.analyze(selected_ticker)

        # 4. 수동 선택 필요
        return {
            "error": "종목 선택 필요",
            "input": input_text,
            "message": "여러 종목이 검색되었습니다. 하나를 선택해주세요.",
            "suggestions": suggestions,
            "formatted_suggestions": self.suggester.format_suggestions(suggestions)
        }

    def interactive_analyze(self, input_text: str) -> Dict:
        """
        대화형 분석 (CLI용)
        """

        result = self.analyze_with_suggestion(input_text, auto_select=True)

        # 수동 선택이 필요한 경우
        if result.get('error') == '종목 선택 필요':
            print("\n" + "="*60)
            print("종목 검색 결과")
            print("="*60)
            print(result['formatted_suggestions'])
            print("\n번호를 입력하여 선택하거나, 0을 입력하여 취소하세요.")

            while True:
                try:
                    choice = input("선택: ").strip()

                    if choice == '0':
                        return {
                            "error": "사용자가 취소함",
                            "input": input_text,
                            "message": "분석이 취소되었습니다."
                        }

                    idx = int(choice) - 1
                    if 0 <= idx < len(result['suggestions']):
                        selected = result['suggestions'][idx]
                        print(f"\n✅ 선택됨: {selected['name']} ({selected['ticker']})")
                        print("="*60)

                        # 선택된 종목 분석
                        return self.orchestrator.analyze(selected['ticker'])
                    else:
                        print("❌ 잘못된 번호입니다. 다시 선택해주세요.")

                except ValueError:
                    print("❌ 숫자를 입력해주세요.")
                except KeyboardInterrupt:
                    return {
                        "error": "사용자가 취소함",
                        "input": input_text,
                        "message": "분석이 취소되었습니다."
                    }

        return result


def analyze_stock(input_text: str, interactive: bool = False) -> Dict:
    """
    주식 분석 메인 함수

    Args:
        input_text: 티커 또는 회사명
        interactive: 대화형 모드 여부

    Returns:
        분석 결과
    """
    analyzer = InteractiveAnalyzer()

    if interactive:
        return analyzer.interactive_analyze(input_text)
    else:
        return analyzer.analyze_with_suggestion(input_text)


# 테스트 코드
if __name__ == "__main__":
    import sys

    print("="*70)
    print("대화형 주식 분석 시스템")
    print("="*70)

    if len(sys.argv) > 1:
        # 명령행 인자로 티커 제공
        input_text = ' '.join(sys.argv[1:])
        print(f"\n입력: {input_text}")
    else:
        # 대화형 입력
        print("\n종목명 또는 티커를 입력하세요.")
        print("예시: 삼성전자, AAPL, 네이버, TSLA")
        input_text = input("\n종목: ").strip()

    if input_text:
        print("\n분석을 시작합니다...")
        print("-"*70)

        result = analyze_stock(input_text, interactive=True)

        print("\n" + "="*70)
        print("분석 결과")
        print("="*70)

        if 'error' in result:
            print(f"❌ 오류: {result['error']}")
            if 'message' in result:
                print(f"   {result['message']}")
        else:
            # 정상 분석 결과
            if 'final_decision' in result:
                decision = result['final_decision']
                print(f"\n종목: {result.get('company_name', result['ticker'])} ({result['ticker']})")
                print(f"최종 신호: {decision.get('final_signal', 'N/A')}")
                print(f"신뢰도: {decision.get('final_confidence', 0):.1f}/10")
                print(f"근거: {decision.get('reasoning', 'N/A')}")

                if decision.get('key_risks'):
                    print(f"\n주요 리스크:")
                    for risk in decision['key_risks']:
                        print(f"  - {risk}")

            # 전체 결과를 JSON으로 저장할지 물어보기
            save = input("\n\n결과를 파일로 저장하시겠습니까? (y/n): ").strip().lower()
            if save == 'y':
                from datetime import datetime as _dt
                import re as _re
                timestamp = _dt.now().strftime('%Y%m%d_%H%M%S')
                # 크로스 플랫폼 안전 파일명: 영숫자/점/하이픈/언더스코어만 허용
                safe_ticker = _re.sub(r'[^A-Za-z0-9._-]', '_', result['ticker'])
                filename = f"analysis_{safe_ticker}_{timestamp}.json"
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)
                print(f"✅ 저장됨: {filename}")
    else:
        print("종목을 입력하지 않았습니다.")