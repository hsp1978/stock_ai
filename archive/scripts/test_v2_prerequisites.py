#!/usr/bin/env python3
"""
V2.0 사전 준비사항 테스트 스크립트
모든 필수 구성요소가 준비되었는지 확인
"""

import sys
import os
import json
import time
from datetime import datetime

# 색상 코드
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'  # No Color


def print_header(title):
    print(f"\n{BLUE}{'='*50}{NC}")
    print(f"{BLUE}{title}{NC}")
    print(f"{BLUE}{'='*50}{NC}")


def check_status(condition, success_msg, fail_msg, is_critical=True):
    """상태 체크 및 출력"""
    if condition:
        print(f"{GREEN}✓{NC} {success_msg}")
        return True
    else:
        if is_critical:
            print(f"{RED}✗{NC} {fail_msg}")
        else:
            print(f"{YELLOW}⚠{NC} {fail_msg}")
        return False


def test_python_version():
    """Python 버전 확인"""
    print_header("1. Python 버전 확인")

    version = sys.version_info
    current = f"{version.major}.{version.minor}.{version.micro}"

    is_valid = version.major >= 3 and version.minor >= 10
    check_status(
        is_valid,
        f"Python {current} (3.10+ 요구사항 충족)",
        f"Python {current} (3.10+ 필요)",
        is_critical=True
    )

    return is_valid


def test_required_packages():
    """필수 패키지 설치 확인"""
    print_header("2. 필수 패키지 확인")

    packages = {
        "pandas": ("데이터 처리", True),
        "numpy": ("수치 계산", True),
        "yfinance": ("주가 데이터", True),
        "streamlit": ("Web UI", True),
        "fastapi": ("API 서버", True),
        "google.generativeai": ("Gemini API", True),
        "openai": ("OpenAI GPT-4o", True),
        "mcp": ("MCP 서버", False),  # V2.0용, 아직 선택
    }

    all_installed = True
    critical_missing = False

    for package, (description, is_critical) in packages.items():
        try:
            if package == "google.generativeai":
                import google.generativeai
            else:
                __import__(package)
            check_status(True, f"{package} ({description})", "")
        except ImportError:
            check_status(
                False,
                "",
                f"{package} 미설치 ({description}) - pip install {package}",
                is_critical
            )
            if is_critical:
                critical_missing = True
            all_installed = False

    return not critical_missing


def test_api_keys():
    """API Key 설정 확인"""
    print_header("3. API Keys 확인")

    env_files = [
        "chart_agent_service/.env",
        ".env"
    ]

    keys_found = {}
    env_file_found = False

    # .env 파일 찾기
    for env_file in env_files:
        if os.path.exists(env_file):
            env_file_found = True
            print(f"   .env 파일 위치: {env_file}")

            # 파일 읽기
            with open(env_file, 'r') as f:
                for line in f:
                    if 'GEMINI_API_KEY' in line and '=' in line:
                        keys_found['GEMINI'] = True
                    if 'OPENAI_API_KEY' in line and '=' in line:
                        keys_found['OPENAI'] = True
            break

    if not env_file_found:
        print(f"{YELLOW}⚠{NC} .env 파일 없음")

    # 환경변수에서도 확인
    if not keys_found.get('GEMINI'):
        keys_found['GEMINI'] = bool(os.getenv('GEMINI_API_KEY'))
    if not keys_found.get('OPENAI'):
        keys_found['OPENAI'] = bool(os.getenv('OPENAI_API_KEY'))

    # 결과 출력
    gemini_ok = check_status(
        keys_found.get('GEMINI', False),
        "Gemini API key 설정됨 (기존)",
        "Gemini API key 없음 - https://makersuite.google.com/app/apikey",
        is_critical=True
    )

    openai_ok = check_status(
        keys_found.get('OPENAI', False),
        "OpenAI API key 설정됨 (V2.0 필수)",
        "OpenAI API key 없음 - https://platform.openai.com/api-keys (V2.0 필수)",
        is_critical=False  # 아직 V2.0 개발 전이므로 경고만
    )

    return gemini_ok


def test_ollama():
    """Ollama 설치 및 실행 확인"""
    print_header("4. Ollama (로컬 LLM) 확인")

    import subprocess
    import requests

    # Ollama 설치 확인
    try:
        result = subprocess.run(['ollama', '--version'], capture_output=True, text=True)
        ollama_installed = result.returncode == 0
    except FileNotFoundError:
        ollama_installed = False

    if not ollama_installed:
        check_status(
            False,
            "",
            "Ollama 미설치 - curl -fsSL https://ollama.com/install.sh | sh",
            is_critical=False
        )
        return False
    else:
        print(f"{GREEN}✓{NC} Ollama 설치됨")

    # Ollama 서버 실행 확인
    try:
        response = requests.get('http://localhost:11434/api/tags', timeout=2)
        server_running = response.status_code == 200

        if server_running:
            models = response.json().get('models', [])
            print(f"{GREEN}✓{NC} Ollama 서버 실행 중")

            if models:
                print(f"   설치된 모델 ({len(models)}개):")
                for model in models[:3]:  # 최대 3개만 표시
                    name = model.get('name', 'unknown')
                    size = model.get('size', 0) / (1024**3)  # GB로 변환
                    print(f"   - {name} ({size:.1f}GB)")

                # 권장 모델 확인
                model_names = [m.get('name', '') for m in models]
                has_recommended = any('mistral' in m or 'llama' in m for m in model_names)

                if not has_recommended:
                    print(f"{YELLOW}⚠{NC} 권장 모델 없음. 설치: ollama pull mistral:7b")
            else:
                print(f"{YELLOW}⚠{NC} 모델 없음. 설치: ollama pull mistral:7b")
        else:
            print(f"{YELLOW}⚠{NC} Ollama 서버 응답 오류")
    except requests.exceptions.RequestException:
        check_status(
            False,
            "",
            "Ollama 서버 미실행 - 다른 터미널에서: ollama serve",
            is_critical=False
        )
        server_running = False

    return ollama_installed and server_running


def test_system_resources():
    """시스템 리소스 확인"""
    print_header("5. 시스템 리소스 확인")

    import psutil

    # CPU 확인
    cpu_count = psutil.cpu_count()
    cpu_ok = check_status(
        cpu_count >= 4,
        f"CPU: {cpu_count} cores (충분)",
        f"CPU: {cpu_count} cores (4+ 권장)",
        is_critical=False
    )

    # 메모리 확인
    mem = psutil.virtual_memory()
    mem_gb = mem.total / (1024**3)
    mem_available_gb = mem.available / (1024**3)
    mem_ok = check_status(
        mem_gb >= 8,
        f"RAM: {mem_gb:.1f}GB (충분), 사용 가능: {mem_available_gb:.1f}GB",
        f"RAM: {mem_gb:.1f}GB (8GB+ 권장)",
        is_critical=False
    )

    # 디스크 확인
    disk = psutil.disk_usage('/home/ubuntu' if os.path.exists('/home/ubuntu') else '/')
    disk_free_gb = disk.free / (1024**3)
    disk_ok = check_status(
        disk_free_gb >= 20,
        f"디스크 여유: {disk_free_gb:.1f}GB (충분)",
        f"디스크 여유: {disk_free_gb:.1f}GB (20GB+ 권장)",
        is_critical=False
    )

    return cpu_ok and mem_ok and disk_ok


def test_api_connectivity():
    """API 연결 테스트"""
    print_header("6. API 연결 테스트")

    import requests

    tests = []

    # 1. Gemini API 테스트
    gemini_key = os.getenv('GEMINI_API_KEY')
    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content("Say 'OK' if you're working")
            gemini_ok = 'OK' in response.text or len(response.text) > 0
            check_status(
                gemini_ok,
                "Gemini API 연결 성공",
                "Gemini API 연결 실패"
            )
            tests.append(gemini_ok)
        except Exception as e:
            check_status(
                False,
                "",
                f"Gemini API 오류: {str(e)[:50]}"
            )
            tests.append(False)
    else:
        print(f"{YELLOW}⚠{NC} Gemini API key 없어서 테스트 스킵")

    # 2. OpenAI API 테스트
    openai_key = os.getenv('OPENAI_API_KEY')
    if openai_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Reply with 'OK' only"}],
                max_tokens=10
            )
            openai_ok = 'OK' in response.choices[0].message.content
            check_status(
                openai_ok,
                "OpenAI API 연결 성공",
                "OpenAI API 연결 실패"
            )
            tests.append(openai_ok)
        except Exception as e:
            error_msg = str(e)[:50]
            if "api_key" in error_msg.lower():
                print(f"{YELLOW}⚠{NC} OpenAI API key 없음 (V2.0에서 필요)")
            else:
                check_status(
                    False,
                    "",
                    f"OpenAI API 오류: {error_msg}"
                )
            tests.append(False)
    else:
        print(f"{YELLOW}⚠{NC} OpenAI API key 없어서 테스트 스킵 (V2.0에서 필요)")

    # 3. FastAPI 서버 테스트
    try:
        response = requests.get('http://localhost:8100/', timeout=2)
        fastapi_ok = response.status_code == 200
        check_status(
            fastapi_ok,
            "FastAPI 서버 실행 중",
            "FastAPI 서버 응답 없음"
        )
        tests.append(fastapi_ok)
    except:
        check_status(
            False,
            "",
            "FastAPI 서버 미실행 - cd chart_agent_service && python service.py",
            is_critical=False
        )
        tests.append(False)

    return all(tests) if tests else False


def generate_report():
    """최종 보고서 생성"""
    print_header("V2.0 준비 상태 종합 보고서")

    results = {
        "Python 3.10+": test_python_version(),
        "필수 패키지": test_required_packages(),
        "API Keys": test_api_keys(),
        "Ollama": test_ollama(),
        "시스템 리소스": test_system_resources(),
        "API 연결": test_api_connectivity(),
    }

    print_header("준비 상태 요약")

    total = len(results)
    passed = sum(results.values())

    for item, status in results.items():
        if status:
            print(f"{GREEN}✓{NC} {item}")
        else:
            print(f"{RED}✗{NC} {item}")

    score_percentage = (passed / total) * 100

    print(f"\n{'='*50}")
    print(f"준비 점수: {passed}/{total} ({score_percentage:.0f}%)")

    if score_percentage == 100:
        print(f"{GREEN}🎉 모든 준비 완료! V2.0 개발을 시작할 수 있습니다.{NC}")
    elif score_percentage >= 70:
        print(f"{YELLOW}⚠ 대부분 준비됨. 일부 항목 확인 필요.{NC}")
    else:
        print(f"{RED}❌ 추가 설정이 필요합니다.{NC}")

    print(f"{'='*50}\n")

    # 다음 단계 안내
    if not results["API Keys"]:
        print("📌 다음 단계:")
        print("1. OpenAI API key 발급: https://platform.openai.com/api-keys")
        print("2. .env 파일에 OPENAI_API_KEY 추가")

    if not results["Ollama"]:
        print("📌 Ollama 설정:")
        print("1. 설치: curl -fsSL https://ollama.com/install.sh | sh")
        print("2. 실행: ollama serve")
        print("3. 모델 다운로드: ollama pull mistral:7b")

    # 결과를 파일로 저장
    report = {
        "timestamp": datetime.now().isoformat(),
        "results": results,
        "score": f"{passed}/{total}",
        "percentage": score_percentage,
        "ready_for_v2": score_percentage >= 70
    }

    with open("v2_readiness_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n📄 상세 보고서 저장됨: v2_readiness_report.json")

    return score_percentage >= 70


def main():
    """메인 실행 함수"""
    print(f"\n{BLUE}Stock AI Agent V2.0 Prerequisites Test{NC}")
    print(f"{BLUE}실행 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{NC}")

    # 준비 상태 확인
    is_ready = generate_report()

    if is_ready:
        print("\n✅ V2.0 개발 준비 완료")
        print("👉 이제 Week 1: MCP 서버 구현을 시작하세요!")
        return 0
    else:
        print("\n⚠️ 추가 준비 필요")
        print("👉 위의 안내에 따라 누락된 항목을 설정하세요.")
        return 1


if __name__ == "__main__":
    sys.exit(main())