#!/usr/bin/env python3
"""
Qwen3-14B HuggingFace 테스트
Qwen2.5-14B와 성능 비교
"""

import os
import sys
import time
import json
import torch
import gc
from datetime import datetime

# 프로젝트 경로 설정
sys.path.insert(0, '/home/ubuntu/stock_auto')

def test_qwen3_huggingface():
    """Qwen3-14B HuggingFace 테스트"""

    print("=" * 70)
    print("Qwen3-14B vs Qwen2.5-14B 성능 비교 테스트")
    print("=" * 70)

    # GPU 메모리 정리
    torch.cuda.empty_cache()
    gc.collect()

    # GPU 정보 출력
    if torch.cuda.is_available():
        print(f"\nGPU: {torch.cuda.get_device_name(0)}")
        print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
        print(f"사용 중: {torch.cuda.memory_allocated(0) / 1024**3:.1f} GB")
        print(f"예약됨: {torch.cuda.memory_reserved(0) / 1024**3:.1f} GB")

    # 테스트 프롬프트 (BAC 분석)
    test_prompt = """당신은 ML Specialist 전문가입니다.
BAC 종목의 머신러닝 분석 결과를 해석하세요.

## ML 예측 결과
- 앙상블 예측: sell (매도)
- 상승 확률: 26.5%
- RandomForest: 매도 (정확도 40.7%)
- XGBoost: 매도 (정확도 44.0%)
- LSTM: 매도 (정확도 48.3%)
- LightGBM: 매도 (정확도 49.5%)
- 백테스트 Sharpe: 0.67
- 최대 손실: -8.2%

## 추가 컨텍스트
- CEO/CFO가 최근 30일간 100만주 매도
- RSI 73.5 (과매수)
- 52주 최고가 대비 -5.6%

다음 JSON 형식으로만 응답하세요:
{
  "signal": "buy/sell/neutral",
  "confidence": 0-10,
  "reasoning": "판단 근거 (핵심 포인트 포함)"
}"""

    results = {}

    # 1. Qwen2.5-14B 테스트 (Ollama)
    print("\n### 1. Qwen2.5-14B (Ollama) 테스트")
    print("-" * 60)

    import requests

    start_time = time.time()
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "qwen2.5:14b-instruct-q4_K_M",
                "prompt": test_prompt,
                "stream": False,
                "options": {"temperature": 0.3}
            },
            timeout=60
        )
        qwen25_time = time.time() - start_time
        qwen25_response = response.json().get('response', '')

        # JSON 파싱
        try:
            if "```json" in qwen25_response:
                json_start = qwen25_response.find("```json") + 7
                json_end = qwen25_response.find("```", json_start)
                json_str = qwen25_response[json_start:json_end].strip()
            elif "{" in qwen25_response:
                json_start = qwen25_response.find("{")
                json_end = qwen25_response.rfind("}") + 1
                json_str = qwen25_response[json_start:json_end]
            else:
                json_str = qwen25_response

            qwen25_parsed = json.loads(json_str)
            print(f"✅ 신호: {qwen25_parsed.get('signal')}")
            print(f"   신뢰도: {qwen25_parsed.get('confidence')}/10")
            print(f"   실행 시간: {qwen25_time:.2f}초")
            print(f"   메모리: ~9GB (q4_K_M)")
            results['qwen25'] = {
                'signal': qwen25_parsed.get('signal'),
                'confidence': qwen25_parsed.get('confidence'),
                'time': qwen25_time,
                'memory': '9GB',
                'reasoning': qwen25_parsed.get('reasoning', '')[:200]
            }
        except:
            print("❌ JSON 파싱 실패")
            results['qwen25'] = {'error': 'parsing failed'}
    except Exception as e:
        print(f"❌ 오류: {e}")
        results['qwen25'] = {'error': str(e)}

    # 2. Qwen3-14B 테스트 (HuggingFace)
    print("\n### 2. Qwen3-14B (HuggingFace) 테스트")
    print("-" * 60)
    print("모델 로딩 중... (첫 실행 시 다운로드 필요)")

    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        # 4-bit quantization 설정
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True
        )

        # 모델 이름 (Qwen/Qwen3-14B는 instruction-tuned 버전)
        model_name = "Qwen/Qwen3-14B"

        # 토크나이저 로드
        print(f"토크나이저 로딩: {model_name}")
        tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            trust_remote_code=True
        )

        # 모델 로드 (4-bit quantization)
        print(f"모델 로딩 (4-bit): {model_name}")
        load_start = time.time()
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            quantization_config=quantization_config,
            device_map="cuda",
            trust_remote_code=True,
            torch_dtype=torch.float16
        )
        load_time = time.time() - load_start
        print(f"✅ 모델 로드 완료 ({load_time:.1f}초)")

        # GPU 메모리 확인
        gpu_memory = torch.cuda.memory_allocated(0) / 1024**3
        print(f"   GPU 메모리 사용: {gpu_memory:.1f} GB")

        # 추론 실행
        print("\n추론 실행 중...")
        start_time = time.time()

        # 입력 토크나이징
        inputs = tokenizer(test_prompt, return_tensors="pt").to("cuda")

        # 생성
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=256,
                temperature=0.3,
                do_sample=True,
                top_p=0.9,
                pad_token_id=tokenizer.eos_token_id
            )

        # 디코딩
        qwen3_response = tokenizer.decode(outputs[0], skip_special_tokens=True)
        # 프롬프트 제거
        qwen3_response = qwen3_response[len(test_prompt):].strip()

        qwen3_time = time.time() - start_time

        # JSON 파싱
        try:
            if "```json" in qwen3_response:
                json_start = qwen3_response.find("```json") + 7
                json_end = qwen3_response.find("```", json_start)
                json_str = qwen3_response[json_start:json_end].strip()
            elif "{" in qwen3_response:
                json_start = qwen3_response.find("{")
                json_end = qwen3_response.rfind("}") + 1
                json_str = qwen3_response[json_start:json_end]
            else:
                json_str = qwen3_response

            qwen3_parsed = json.loads(json_str)
            print(f"✅ 신호: {qwen3_parsed.get('signal')}")
            print(f"   신뢰도: {qwen3_parsed.get('confidence')}/10")
            print(f"   실행 시간: {qwen3_time:.2f}초 (추론만)")
            print(f"   메모리: {gpu_memory:.1f}GB (4-bit)")

            results['qwen3'] = {
                'signal': qwen3_parsed.get('signal'),
                'confidence': qwen3_parsed.get('confidence'),
                'time': qwen3_time,
                'load_time': load_time,
                'memory': f'{gpu_memory:.1f}GB',
                'reasoning': qwen3_parsed.get('reasoning', '')[:200]
            }
        except Exception as e:
            print(f"❌ JSON 파싱 실패: {e}")
            print(f"응답: {qwen3_response[:500]}")
            results['qwen3'] = {'error': 'parsing failed', 'response': qwen3_response[:200]}

        # 모델 메모리 정리
        del model
        del tokenizer
        torch.cuda.empty_cache()
        gc.collect()

    except ImportError as e:
        print(f"❌ 패키지 오류: {e}")
        print("필요한 패키지를 설치하세요:")
        print("pip install transformers accelerate bitsandbytes")
        results['qwen3'] = {'error': 'package missing'}
    except Exception as e:
        print(f"❌ 오류: {e}")
        import traceback
        traceback.print_exc()
        results['qwen3'] = {'error': str(e)}

    # 3. 비교 분석
    print("\n" + "=" * 70)
    print("성능 비교 결과")
    print("=" * 70)

    comparison_table = []

    # Qwen2.5-14B
    if 'qwen25' in results and 'signal' in results['qwen25']:
        comparison_table.append([
            "Qwen2.5-14B",
            results['qwen25']['signal'],
            f"{results['qwen25']['confidence']}/10",
            f"{results['qwen25']['time']:.2f}초",
            results['qwen25']['memory'],
            "Ollama"
        ])

    # Qwen3-14B
    if 'qwen3' in results and 'signal' in results['qwen3']:
        comparison_table.append([
            "Qwen3-14B",
            results['qwen3']['signal'],
            f"{results['qwen3']['confidence']}/10",
            f"{results['qwen3']['time']:.2f}초",
            results['qwen3']['memory'],
            "HuggingFace"
        ])

    # 테이블 출력
    if comparison_table:
        headers = ["모델", "신호", "신뢰도", "추론 시간", "메모리", "플랫폼"]
        col_widths = [max(len(str(row[i]) if i < len(row) else "") for row in [headers] + comparison_table) + 2
                      for i in range(len(headers))]

        # 헤더 출력
        header_line = "|".join(h.ljust(w) for h, w in zip(headers, col_widths))
        print(header_line)
        print("-" * len(header_line))

        # 데이터 출력
        for row in comparison_table:
            print("|".join(str(v).ljust(w) for v, w in zip(row, col_widths)))

    # 개선 효과 분석
    if all(k in results and 'time' in results[k] for k in ['qwen25', 'qwen3']):
        print("\n### 개선 효과")
        time_improvement = (results['qwen25']['time'] - results['qwen3']['time']) / results['qwen25']['time'] * 100

        print(f"추론 속도: ", end="")
        if time_improvement > 0:
            print(f"Qwen3가 {time_improvement:.1f}% 빠름 ✅")
        else:
            print(f"Qwen2.5가 {-time_improvement:.1f}% 빠름")

        # 메모리 비교 (대략적)
        qwen25_mem = 9.0  # GB
        qwen3_mem = float(results['qwen3']['memory'].replace('GB', ''))
        mem_saving = (qwen25_mem - qwen3_mem) / qwen25_mem * 100
        print(f"메모리 사용: Qwen3가 {mem_saving:.1f}% 적게 사용 ✅")

    # 품질 평가
    print("\n### 품질 평가")
    quality_score = {'qwen25': 0, 'qwen3': 0}

    for model_key in ['qwen25', 'qwen3']:
        if model_key in results and 'signal' in results[model_key]:
            # BAC는 sell이 정답
            if results[model_key]['signal'] == 'sell':
                quality_score[model_key] += 3
            # 신뢰도 6-8이 적절
            conf = results[model_key].get('confidence', 0)
            if 6 <= conf <= 8:
                quality_score[model_key] += 2

    print(f"Qwen2.5-14B 품질 점수: {quality_score['qwen25']}/5")
    print(f"Qwen3-14B 품질 점수: {quality_score['qwen3']}/5")

    # 최종 권고
    print("\n" + "=" * 70)
    print("최종 권고사항")
    print("=" * 70)

    if 'qwen3' in results and 'signal' in results['qwen3']:
        print("✅ Qwen3-14B 테스트 성공!")
        print("\n장점:")
        print("- Qwen2.5-32B 수준의 성능 (이론상)")
        print("- 4-bit quantization으로 메모리 효율적")
        print("- 최신 36T 토큰 학습 데이터")

        print("\n단점:")
        print("- 첫 로딩 시간이 김 (모델 다운로드)")
        print("- Ollama 미지원 (별도 서버 필요)")
        print("- 프로덕션 안정성 검증 필요")

        print("\n추천:")
        if quality_score['qwen3'] >= quality_score['qwen25']:
            print("→ Qwen3-14B를 테스트 환경에서 더 검증 후 도입 고려")
        else:
            print("→ 당분간 Qwen2.5-14B 유지, Qwen3 안정화 대기")
    else:
        print("❌ Qwen3-14B 테스트 실패")
        print("→ Qwen2.5-14B 계속 사용 권장")

    # 결과 저장
    results['timestamp'] = datetime.now().isoformat()
    results['quality_score'] = quality_score

    with open("/home/ubuntu/stock_auto/qwen3_test_results.json", "w", encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n테스트 결과가 qwen3_test_results.json에 저장되었습니다.")

    return results

if __name__ == "__main__":
    test_qwen3_huggingface()