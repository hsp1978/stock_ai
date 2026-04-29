#!/usr/bin/env python3
"""
LLM Provider 테스트 스크립트
- Gemini, OpenAI, Ollama 각각 테스트
- 한국 주식 분석 테스트
"""

import os
import sys
import json
from dotenv import load_dotenv

sys.path.insert(0, 'stock_analyzer')

# .env 파일 로드
load_dotenv('stock_analyzer/.env')

from multi_agent import MultiAgentOrchestrator

def test_provider(provider_name: str, ticker: str = "328130.KQ"):
    """특정 LLM provider로 분석 테스트"""
    print(f"\n{'='*70}")
    print(f"Testing {provider_name.upper()} Provider")
    print('='*70)
    print(f"Ticker: {ticker} (루닛)")

    try:
        # Provider별 환경 변수 확인
        if provider_name == "gemini":
            api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
            if not api_key:
                print("❌ GEMINI_API_KEY 또는 GOOGLE_API_KEY 환경 변수가 설정되지 않았습니다.")
                return False
            print("✅ Gemini API key found")

        elif provider_name == "openai":
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                print("❌ OPENAI_API_KEY 환경 변수가 설정되지 않았습니다.")
                return False
            print("✅ OpenAI API key found")

        elif provider_name == "ollama":
            print("✅ Ollama (로컬 서비스)")

        # 오케스트레이터 생성
        orchestrator = MultiAgentOrchestrator(llm_provider=provider_name)

        print(f"\n분석 시작...")
        result = orchestrator.analyze(ticker)

        # 결과 출력
        if 'error' in result:
            print(f"\n❌ 에러: {result['error']}")
            return False

        if 'final_decision' in result:
            decision = result['final_decision']
            print(f"\n✅ 분석 완료!")
            print(f"  최종 신호: {decision.get('final_signal', 'N/A')}")
            print(f"  신뢰도: {decision.get('final_confidence', 0):.1f}/10")
            print(f"  합의: {decision.get('consensus', 'N/A')}")

            # 에이전트별 결과 요약
            if 'agent_results' in result:
                print("\n에이전트별 결과:")
                for agent in result['agent_results']:
                    provider = agent.get('llm_provider', 'unknown')
                    status = "✓" if not agent.get('error') else "✗"
                    print(f"  {status} {agent['agent']} ({provider}): {agent['signal']} ({agent['confidence']:.1f}/10)")
                    if agent.get('error'):
                        print(f"     -> {agent['error'][:50]}...")

            return True

        print("⚠️ 분석 결과를 받지 못했습니다.")
        return False

    except Exception as e:
        print(f"❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_mixed_providers():
    """에이전트별로 다른 provider 사용 테스트"""
    print(f"\n{'='*70}")
    print("Testing MIXED Providers (에이전트별 다른 LLM)")
    print('='*70)

    # API 키 확인
    has_gemini = bool(os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY'))
    has_openai = bool(os.getenv('OPENAI_API_KEY'))

    if not has_gemini and not has_openai:
        print("⚠️ Gemini 또는 OpenAI API 키가 없어 혼합 테스트를 건너뜁니다.")
        return

    # 에이전트별 provider 설정
    agent_providers = {}

    if has_gemini:
        agent_providers["Technical Analyst"] = "gemini"
        agent_providers["Value Investor"] = "gemini"
        print("  Technical Analyst → Gemini")
        print("  Value Investor → Gemini")

    if has_openai:
        agent_providers["ML Specialist"] = "openai"
        agent_providers["Event Analyst"] = "openai"
        print("  ML Specialist → OpenAI")
        print("  Event Analyst → OpenAI")

    print("  나머지 에이전트 → Ollama")

    try:
        # 오케스트레이터 생성 (기본은 ollama, 특정 에이전트만 다른 provider)
        orchestrator = MultiAgentOrchestrator(
            llm_provider="ollama",
            agent_providers=agent_providers
        )

        ticker = "005930.KS"  # 삼성전자
        print(f"\n테스트 종목: {ticker} (삼성전자)")
        print("분석 시작...")

        result = orchestrator.analyze(ticker)

        if 'final_decision' in result:
            decision = result['final_decision']
            print(f"\n✅ 분석 완료!")
            print(f"  최종 신호: {decision.get('final_signal', 'N/A')}")
            print(f"  신뢰도: {decision.get('final_confidence', 0):.1f}/10")

            # Provider별 그룹화
            if 'agent_results' in result:
                provider_groups = {}
                for agent in result['agent_results']:
                    provider = agent.get('llm_provider', 'unknown')
                    if provider not in provider_groups:
                        provider_groups[provider] = []
                    provider_groups[provider].append(agent)

                print("\nProvider별 에이전트 결과:")
                for provider, agents in provider_groups.items():
                    print(f"\n  [{provider.upper()}]")
                    for agent in agents:
                        status = "✓" if not agent.get('error') else "✗"
                        print(f"    {status} {agent['agent']}: {agent['signal']} ({agent['confidence']:.1f}/10)")

            return True

        return False

    except Exception as e:
        print(f"❌ 테스트 실패: {e}")
        return False

def main():
    """메인 테스트 함수"""
    print("=" * 70)
    print("LLM Provider 선택 기능 테스트")
    print("=" * 70)

    # 현재 설정된 기본 provider 확인
    default_provider = os.getenv('DEFAULT_LLM_PROVIDER', 'ollama')
    print(f"\n기본 Provider (DEFAULT_LLM_PROVIDER): {default_provider}")

    # 각 provider 테스트
    providers_to_test = []

    # Provider별로 사용 가능 여부 확인
    if os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY'):
        providers_to_test.append("gemini")
    else:
        print("\n⚠️ Gemini API 키가 없어 Gemini 테스트를 건너뜁니다.")

    if os.getenv('OPENAI_API_KEY'):
        providers_to_test.append("openai")
    else:
        print("⚠️ OpenAI API 키가 없어 OpenAI 테스트를 건너뜁니다.")

    # Ollama는 항상 테스트 (로컬 서비스)
    providers_to_test.append("ollama")

    # 각 provider로 테스트
    results = {}
    for provider in providers_to_test:
        success = test_provider(provider)
        results[provider] = success

    # 혼합 provider 테스트
    print("\n" + "="*70)
    test_mixed_providers()

    # 결과 요약
    print("\n" + "="*70)
    print("테스트 결과 요약")
    print("="*70)
    for provider, success in results.items():
        status = "✅ 성공" if success else "❌ 실패"
        print(f"  {provider.upper()}: {status}")

    # 사용 안내
    print("\n" + "="*70)
    print("사용 방법")
    print("="*70)
    print("""
1. 환경 변수로 기본 Provider 설정:
   export DEFAULT_LLM_PROVIDER=gemini  # 또는 openai, ollama

2. Python 코드에서 직접 설정:
   # 모든 에이전트가 같은 provider 사용
   orchestrator = MultiAgentOrchestrator(llm_provider="gemini")

   # 에이전트별로 다른 provider 사용
   orchestrator = MultiAgentOrchestrator(
       llm_provider="ollama",  # 기본값
       agent_providers={
           "Technical Analyst": "gemini",
           "ML Specialist": "openai"
       }
   )

3. 필요한 API 키 설정:
   - Gemini: GEMINI_API_KEY 또는 GOOGLE_API_KEY
   - OpenAI: OPENAI_API_KEY
   - Ollama: 로컬 서비스 실행 (기본 포트 11434)
    """)

if __name__ == "__main__":
    main()