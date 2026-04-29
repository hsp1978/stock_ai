#!/usr/bin/env python3
"""
002810.KS (삼영무역) 버그 수정 확인 테스트
- 0명 매수인데 buy 신호 나오는 버그 수정 확인
- Ollama 장애 시 적절한 경고 표시 확인
"""

import sys
import json
from datetime import datetime

sys.path.insert(0, 'stock_analyzer')

from multi_agent import MultiAgentOrchestrator

print("=" * 80)
print("002810.KS (삼영무역) 분석 - 버그 수정 확인")
print("=" * 80)

# 테스트 종목
ticker = "002810.KS"
print(f"\n테스트 종목: {ticker}")
print(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# 1. 오케스트레이터 생성 (Ollama 사용)
print("\n[1단계] MultiAgent 초기화...")
orchestrator = MultiAgentOrchestrator(llm_provider="ollama")

# 2. 분석 실행
print("\n[2단계] 분석 실행...")
result = orchestrator.analyze(ticker)

# 3. 결과 검증
print("\n" + "=" * 80)
print("분석 결과 검증")
print("=" * 80)

if 'error' in result:
    print(f"❌ 에러 발생: {result['error']}")
    if 'suggestions' in result:
        print("추천 종목:")
        for sug in result['suggestions'][:3]:
            print(f"  - {sug['name']} ({sug['ticker']})")
else:
    # 에이전트 결과 요약
    if 'agent_results' in result:
        print("\n📊 에이전트 분석 결과:")
        print("-" * 50)

        failed_count = 0
        success_count = 0

        for agent in result['agent_results']:
            status = "✓" if not agent.get('error') and agent.get('confidence', 0) > 0 else "✗"

            if status == "✓":
                success_count += 1
            else:
                failed_count += 1

            print(f"  {status} {agent['agent']:20s} : {agent['signal']:8s} (신뢰도: {agent['confidence']:.1f}/10)")

            if agent.get('error'):
                error_msg = agent['error'][:50] if len(agent['error']) > 50 else agent['error']
                print(f"      └─ 오류: {error_msg}")

        print(f"\n  성공: {success_count}개, 실패: {failed_count}개")

    # 최종 결정 분석
    if 'final_decision' in result:
        decision = result['final_decision']
        print("\n🎯 최종 결정:")
        print("-" * 50)
        print(f"  신호: {decision.get('final_signal', 'N/A')}")
        print(f"  신뢰도: {decision.get('final_confidence', 0):.1f}/10")
        print(f"  의견 분포: {decision.get('consensus', 'N/A')}")

        # 신호 분포
        dist = decision.get('signal_distribution', {})
        print(f"\n  상세 분포:")
        print(f"    매수: {dist.get('buy', 0)}명")
        print(f"    매도: {dist.get('sell', 0)}명")
        print(f"    중립: {dist.get('neutral', 0)}명")

        # 검증: 0명 매수인데 buy 신호인지 체크
        if dist.get('buy', 0) == 0 and decision.get('final_signal') == 'buy':
            print("\n  ❌❌❌ 버그 재현: 0명 매수인데 buy 신호 발생!")
        elif dist.get('buy', 0) == 0 and dist.get('sell', 0) == 0:
            if decision.get('final_signal') == 'neutral':
                print("\n  ✅ 정상: 전원 중립 → neutral 신호")
            else:
                print(f"\n  ⚠️ 의심: 전원 중립인데 {decision.get('final_signal')} 신호")
        else:
            print("\n  ✅ 정상: 에이전트 의견과 일치")

        # 시스템 장애 체크
        if decision.get('system_failure'):
            print("\n  🔴 시스템 장애 감지됨")

        # 리스크 표시
        risks = decision.get('key_risks', [])
        if risks:
            print(f"\n  리스크:")
            for risk in risks[:3]:
                print(f"    - {risk}")

    # 경고 메시지
    warnings = result.get('warnings', [])
    if warnings:
        print("\n⚠️ 경고:")
        for warning in warnings:
            print(f"  - {warning}")

# 4. 개선 확인 사항
print("\n" + "=" * 80)
print("개선 사항 확인")
print("=" * 80)

improvements = {
    "에이전트 전원 장애 감지": False,
    "0명 매수 → buy 방지": False,
    "Ollama 헬스체크": False,
    "시스템 장애 경고": False,
    "중립 신호 정상 출력": False
}

# 체크 로직
if 'final_decision' in result:
    decision = result['final_decision']
    dist = decision.get('signal_distribution', {})

    # 1. 전원 장애 감지
    if decision.get('system_failure') or 'valid_agent_count' in decision:
        improvements["에이전트 전원 장애 감지"] = True

    # 2. 0명 매수 → buy 방지
    if dist.get('buy', 0) == 0 and decision.get('final_signal') != 'buy':
        improvements["0명 매수 → buy 방지"] = True

    # 3. Ollama 헬스체크 (경고 메시지로 확인)
    if any('Ollama' in str(w) for w in result.get('warnings', [])):
        improvements["Ollama 헬스체크"] = True

    # 4. 시스템 장애 경고
    if any('장애' in str(r) for r in decision.get('key_risks', [])):
        improvements["시스템 장애 경고"] = True

    # 5. 중립 신호 정상 출력
    if dist.get('buy', 0) == 0 and dist.get('sell', 0) == 0:
        if decision.get('final_signal') == 'neutral':
            improvements["중립 신호 정상 출력"] = True

print("\n체크리스트:")
for item, status in improvements.items():
    icon = "✅" if status else "❌"
    print(f"  {icon} {item}")

success_count = sum(1 for v in improvements.values() if v)
total_count = len(improvements)
print(f"\n달성률: {success_count}/{total_count} ({success_count/total_count*100:.0f}%)")

print("\n" + "=" * 80)
print("테스트 완료")
print("=" * 80)